"""API route for generating documentation from a repository using Gemini.

'Sandbox' implementation with Job Polling:
  - POST /api/generate-docs  → returns { job_id } immediately
  - GET  /api/generate-docs/{job_id} → returns current job status
  - Heavy work (git clone + Gemini Pro) runs in a FastAPI BackgroundTask
  - In-memory jobs dict stores results keyed by UUID
  - Cleanup via shutil.rmtree in a finally block
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import traceback
import urllib.request
import uuid
from typing import Any, Dict, List

# Optional: Playwright for live app scraping (graceful fallback if not installed)
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from google import genai
from google.api_core import exceptions
from pydantic import BaseModel, SecretStr

from openhands.core.logger import openhands_logger as logger
from openhands.integrations.provider import PROVIDER_TOKEN_TYPE, ProviderType
from openhands.server.dependencies import get_dependencies
from openhands.server.user_auth import get_provider_tokens

app = APIRouter(prefix='/api', dependencies=get_dependencies())


# ---------------------------------------------------------------------------
# In-Memory Job Store
# ---------------------------------------------------------------------------
jobs: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Request Model
# ---------------------------------------------------------------------------
class DocRequest(BaseModel):
    provider: str   # 'github' or 'gitlab'
    repo_name: str  # e.g., 'owner/repo'



# ---------------------------------------------------------------------------
# System Prompt – Enterprise Readme Architect (Structural Filter + Safe Syntax)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """
You are a **Senior Technical Writer** producing an **Enterprise Readme-Style User Manual**.

## CRITICAL RULES (READ FIRST)

### STRUCTURAL FILTER (Anti-Bloat)
- The sidebar manifest has EXACTLY 5 categories. Generate ONLY the sections listed.
- **NEVER** create a section for an individual component, hook, utility, or helper file.
- **Consolidate** sub-components into their parent module.
  - BAD:  Separate sections for `ActiveLoads`, `FiltersComponent`, `useTripsHook`, `TripTable`.
  - GOOD: ONE section called "Trip Management" that covers all of those.
- Total output should be **5–15 module sections maximum**.
- **Delete** any empty, redundant, or purely technical notes that don’t help a user understand the product.

### SAFE MERMAID SYNTAX (Anti-Crash)
- Use ONLY standard rectangles `["Label"]` for all nodes.
- **NEVER** use `(())`, `({})`, `{{}}`, `([ ])`, or `>` shapes.
- Every label MUST be in double quotes: `A["User"] --> B["Login Page"]`.
- Limit every diagram to **10 nodes maximum**.
- BAD:  `User((User)) --> Login{Check Auth}` ← WILL CRASH.
- GOOD: `A["User"] --> B["Login Page"] --> C["Dashboard"]`.

## YOUR DATA SOURCES (priority order)
1. **Sidebar Structure** – The JSON manifest defines the EXACT categories and modules. Follow it literally.
2. **Probed Live App State** – Clicked tabs, opened modals, captured table headers. HIGHEST-FIDELITY.
3. **Data Flow Traces** – Form onSubmit → API endpoint mappings.
4. **UI Action Map** – Static code analysis of tabs, buttons, form fields.
5. **Project Identity** – Routes, tech stack, login selectors.
6. **Source Code** – Full codebase with [CORE_LOGIC] files.

## OUTPUT FORMAT
Generate ONE continuous Markdown document. For EACH module in the sidebar manifest:
`<!-- MODULE: [slug] -->`

## DOCUMENTATION TEMPLATE PER MODULE

```
<!-- MODULE: [slug] -->
# [Module Title]

> **What it is:** [1 sentence explaining the feature.]
> **Who uses it:** [Persona: Broker, Carrier, Admin, All Users]

---

## Visual Walkthrough
Describe the page layout as if guiding a new employee:
- "To the left, you will find the filter panel..."
- "In the center, a data table displays records with columns for..."
- "At the top, a tab bar lets you switch between..."

## Tab Guide
For each tab:
> When the user clicks the **[Tab Name]** tab, the system displays [description].
> The table shows columns: **[Col1]**, **[Col2]**, **[Col3]**.
> From here, the user can:
> - Click **[Button A]** to [action A]
> - Click **[Button B]** to [action B]

## Step-by-Step Operations

### How to Create a [Item]
1. Click the **[Button Name]** button.
2. A modal appears titled "[Title]" with fields: [list].
3. Fill in the required fields.
4. Click **[Submit]** to save.

> [!IMPORTANT]
> After submission, the system sends data to `[API Endpoint]` via [METHOD], which creates a new record.

### How to Edit a [Item]
1. Click the row or the **Edit** icon.
2. Modify the desired fields.
3. Click **Save** to apply changes.

> [!NOTE]
> Changes are saved immediately. There is no “Draft” state.

## Data Lifecycle
```mermaid
graph LR
    A["User Action"] --> B["Form Validation"]
    B --> C["API Request"]
    C --> D["Server Processing"]
    D --> E["Database Updated"]
    E --> F["UI Refreshes"]
```

## Field Guide
| Technical Field | Business Meaning | Example |
|---|---|---|
| `field_key` | Human description | Example value |
```

## WRITING RULES
1. **Follow the sidebar manifest EXACTLY.** One `<!-- MODULE: slug -->` per entry. No extras.
2. **Consolidate, don’t fragment.** Group hooks, utilities, and sub-components under their parent module.
3. **No jargon.** Don’t create “Non-Coder Logic Parsing” pages. Bake plain language INTO the user guide.
4. **What / When / How:** Every feature uses: What it is (1 sentence) → When to use it (1 sentence) → Step-by-Step (numbered).
5. **Callouts:** Use `> [!IMPORTANT]` for critical notes, `> [!NOTE]` for tips. Never plain paragraphs for warnings.
6. **Visual first.** Describe what the user SEES before what they can DO.
7. **Probed data wins.** Use tab_states and sub_features over static analysis.
8. **Safe Mermaid ONLY.** Rectangles `[]`, double-quoted labels, max 10 nodes. No special shapes.
9. **Persona tone.** Broker = business language. Carrier = logistics language. Admin = system language.
"""


# ---------------------------------------------------------------------------
# Engineer Blueprint Prompt (Safe Syntax + Enterprise Style)
# ---------------------------------------------------------------------------
ENGINEER_BLUEPRINT_PROMPT = """
You are a **Senior Software Architect**. Create a technical reference titled "Engineer’s Blueprint".

## MERMAID SAFETY RULES (MANDATORY)
- Use ONLY standard rectangles `["Label"]`. No `(())`, `({})`, `{{}}` shapes.
- Every label MUST be in double quotes.
- Limit each diagram to 10 nodes maximum.
- For sequence diagrams, use only simple participant names (no spaces or special chars).
- BAD:  `User((User)) --> Auth{Check}`
- GOOD: `A["User"] --> B["Auth Service"] --> C["Database"]`

## SECTIONS

# Engineer’s Blueprint

## 1. Tech Stack Audit
| Library | Version | Purpose |
|---|---|---|

## 2. Authentication Flow
```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant A as API
    participant D as Database
    U->>F: Enter credentials
    F->>A: POST /auth/login
    A->>D: Validate credentials
    D-->>A: User record
    A-->>F: JWT Token
    F->>F: Store token locally
```

> [!IMPORTANT]
> Document the ACTUAL auth method found in the code (JWT, session, OAuth, etc.).

## 3. System Architecture
```mermaid
graph LR
    A["User Browser"] --> B["React Frontend"]
    B --> C["API Gateway"]
    C --> D["Backend Services"]
    D --> E["Database"]
```

> [!NOTE]
> Limit to high-level flow. Show only the 5 major layers.

## 4. Environment Configuration
| Key | Purpose | Required | Default |
|---|---|---|---|

## 5. API Surface Map
| Method | Endpoint | Handler | Description |
|---|---|---|---|

## 6. State Management
Explain the pattern (Redux, Zustand, Context) with a safe diagram:
```mermaid
graph LR
    A["Component"] --> B["Action/Hook"]
    B --> C["Store/Reducer"]
    C --> D["State"]
    D --> A
```

## 7. Folder Structure
Document the project’s directory architecture and explain each top-level folder.

## 8. Integration Guide
- Base URL configuration
- Auth header injection
- Error handling pattern
- Service layer structure

**RULES:** Document ONLY what exists in the code. Use safe Mermaid syntax everywhere.
"""


# ---------------------------------------------------------------------------
# Helpers – Clone & Read (blocking)
# ---------------------------------------------------------------------------
def _build_clone_url(
    provider: str, repo_name: str, git_token: str | None, git_host: str | None
) -> str:
    """Build an authenticated clone URL based on provider and optional custom host/token."""

    # Defaults
    if provider == 'github':
        host = git_host or 'github.com'
        if git_token:
            return f'https://{git_token}@{host}/{repo_name}.git'
        return f'https://{host}/{repo_name}.git'

    elif provider == 'gitlab':
        host = git_host or 'gitlab.com'
        # Clean host just in case (remove protocol/slashes)
        host = host.replace('https://', '').replace('http://', '').rstrip('/')

        if git_token:
            return f'https://oauth2:{git_token}@{host}/{repo_name}.git'
        return f'https://{host}/{repo_name}.git'

    raise ValueError(f"Unsupported provider: {provider}")


def _clone_repo(clone_url: str, dest: str) -> None:
    """Run git clone synchronously. Raises on failure."""
    logger.info(f'[CLONE] Cloning into {dest} …')
    result = subprocess.run(
        ['git', 'clone', '--depth', '1', clone_url, dest],
        capture_output=True,
        text=True,
        timeout=320,
        env={
            **os.environ,
            'GIT_TERMINAL_PROMPT': '0',
        },
    )
    if result.returncode != 0:
        raise RuntimeError(
            f'git clone failed (exit {result.returncode}): {result.stderr.strip()}'
        )
    logger.info('[CLONE] Clone completed successfully.')


def _read_repo_files(repo_dir: str) -> str:
    """Nuclear File Scan – Reads EVERY relevant code file.

    - No skipping logic folders (reads utils, lib, etc.)
    - Adds [VISUAL DETECTED] tags for specific UI components.
    - Enforces > 50,000 char context limit.
    """
    print('DEBUG: Starting NUCLEAR VISUAL File Scan...')

    # 1. Target roots – where the code lives
    target_roots = [
        'src', 'app', 'pages', 'components', 'features',
        'services', 'store', 'hooks', 'lib', 'utils'
    ]

    # Only exclude heavy junk
    junk_dirs = {'node_modules', '.git', 'dist', 'build', 'coverage', '.next'}

    # Extensions to read
    code_extensions = ('.tsx', '.ts', '.jsx', '.js', '.py', '.php', '.json', '.prisma')

    # Visual keywords to tag
    visual_keywords = [
        '<BarChart', '<LineChart', '<PieChart', '<AreaChart',
        '<Table', '<Grid', '<List', '<Card', '<Stat', '<Widget',
        '<Modal', '<Dialog', '<Drawer', '<Sidebar', '<Navbar', '<Menu'
    ]

    code_context = ''
    file_count = 0
    total_chars = 0

    # 2. Walk from the root
    for root, dirs, files in os.walk(repo_dir):
        # Remove junk dirs
        dirs[:] = [d for d in dirs if d not in junk_dirs]

        # Check relevance
        is_relevant = any(folder in root for folder in target_roots)

        # 3. Read Files
        for fname in sorted(files):
            if not fname.endswith(code_extensions):
                continue

            # If not in a target root, verify if we should skip?
            # The prompt says "Walk through src, app..." so we prioritize those,
            # but if the project is flat, we might miss things if we are too strict.
            # Let's trust the 'target_roots' list primarily, but also check 'src' presence.
            if not is_relevant and 'src' not in root and 'app' not in root:
                # If it's a root file like 'App.tsx' or config, maybe keep it.
                pass

            file_path = os.path.join(root, fname)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # 4. Content Check
                if len(content) > 20: # Read almost everything
                    rel_path = os.path.relpath(file_path, repo_dir)

                    # Visual Tagging
                    tags = ""
                    for vk in visual_keywords:
                        if vk in content:
                            tags = " [VISUAL DETECTED]"
                            break

                    code_context += (
                        f"\n\n# FILE_START: {rel_path}{tags}\n"
                        f"{content}\n"
                        f"# FILE_END\n"
                    )
                    file_count += 1
                    total_chars += len(content)

            except Exception as exc:
                print(f'Failed to read {fname}: {exc}')

    print(
        f'DEBUG: Scan Complete. '
        f'Read {file_count} files. '
        f'Total Context: {total_chars} chars.'
    )
    logger.info(
        f'[READ] Nuclear scan: {file_count} files, '
        f'{total_chars} chars.'
    )

    # 5. FAIL-SAFE: 50k chars minimum
    if total_chars < 50_000:
        msg = (
            f"Clone Failed: Repository is too small. "
            f"(Read {total_chars} chars, expected > 50,000). "
            f"Check if src/app folders exist."
        )
        logger.error(f'[READ] {msg}')
        raise RuntimeError(msg)

    return code_context


def _build_ui_action_map(repo_dir: str) -> str:
    """Component Auditor – Scans JSX/TSX files to build a UI Action Map.

    Discovers:
    - Tabs / SegmentedControls and their labels
    - Buttons / Links and what they trigger (modals, navigation)
    - Form input fields in Add/Edit modals

    Returns a formatted string ready to inject into the Gemini context.
    """
    print('DEBUG: Starting Component Auditor (UI Action Map)...')

    junk_dirs = {'node_modules', '.git', 'dist', 'build', 'coverage', '.next', 'public', 'assets'}
    ui_extensions = ('.tsx', '.ts', '.jsx', '.js', '.vue')

    # Patterns for discovery
    # Tabs: <Tab label="..."> | <Tabs.TabPane tab="..."> | key: "...", label: "..." | { value: "...", label: "..." }
    tab_patterns = [
        re.compile(r'(?:label|tab|title)\s*[=:]\s*["\']([^"\']{2,40})["\']', re.IGNORECASE),
        re.compile(r'<Tab[^>]*>\s*([^<]{2,40})\s*</Tab', re.IGNORECASE),
        re.compile(r'SegmentedControl[^}]*labels?\s*[=:]\s*\[([^\]]+)\]', re.IGNORECASE),
    ]

    # Buttons: <Button ...>Label</Button> | <button ...>Label</button> | <a ...>Label</a>
    button_pattern = re.compile(
        r'<(?:Button|button|IconButton|Fab|a)\b[^>]*>\s*([^<]{1,60})\s*</(?:Button|button|IconButton|Fab|a)>',
        re.IGNORECASE,
    )
    # Also catch onClick handlers with identifiable actions
    onclick_modal_pattern = re.compile(
        r'onClick\s*=\s*\{[^}]*(?:open|show|toggle|set)\s*([A-Z]\w*(?:Modal|Drawer|Dialog))',
        re.IGNORECASE,
    )

    # Form fields: <Input | <TextField | <Select | <DatePicker | name="..." | label="..." | placeholder="..."
    form_field_patterns = [
        re.compile(
            r'<(?:Input|TextField|TextInput|Select|DatePicker|TimePicker|Checkbox|Switch|Radio|Autocomplete|NumberInput)'
            r'[^>]*(?:label|placeholder|name)\s*=\s*["\']([^"\']{2,50})["\']',
            re.IGNORECASE,
        ),
        re.compile(
            r'(?:label|placeholder)\s*[=:]\s*["\']([^"\']{2,50})["\']',
            re.IGNORECASE,
        ),
    ]

    # Page detection: infer page name from filename or folder
    page_keywords = [
        'page', 'view', 'screen', 'dashboard', 'panel', 'layout',
        'trip', 'driver', 'broker', 'carrier', 'order', 'load',
        'invoice', 'payment', 'profile', 'setting', 'report',
        'customer', 'account', 'fleet', 'dispatch', 'tracking',
    ]

    # Results store: { page_name: { tabs: set, buttons: set, modals: set, fields: set } }
    pages: Dict[str, Dict[str, set]] = {}

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in junk_dirs]

        for fname in sorted(files):
            if not fname.endswith(ui_extensions):
                continue

            file_path = os.path.join(root, fname)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception:
                continue

            if len(content) < 50:
                continue

            # Determine page name
            base_name = os.path.splitext(fname)[0].lower()
            rel_path = os.path.relpath(file_path, repo_dir).lower()

            # Try folder-based naming first (e.g., trips/index.tsx -> Trips)
            parts = rel_path.replace('\\', '/').split('/')
            page_name = None
            for part in reversed(parts[:-1]):  # check folders
                clean = part.replace('-', '').replace('_', '')
                if any(kw in clean for kw in page_keywords):
                    page_name = part.replace('-', ' ').replace('_', ' ').title()
                    break
            if not page_name:
                # Fallback to filename
                clean_base = base_name.replace('-', '').replace('_', '')
                if any(kw in clean_base for kw in page_keywords):
                    page_name = base_name.replace('-', ' ').replace('_', ' ').title()
            if not page_name:
                # If it has UI indicators but no page keyword, use parent folder
                if any(tag in content for tag in ['<Table', '<DataGrid', '<Form', '<Modal', '<Tabs', '<Tab']):
                    page_name = parts[-2].replace('-', ' ').replace('_', ' ').title() if len(parts) > 1 else base_name.title()
                else:
                    continue  # Not a page-level component

            if page_name not in pages:
                pages[page_name] = {'tabs': set(), 'buttons': set(), 'modals': set(), 'fields': set()}

            entry = pages[page_name]

            # --- Tab Discovery ---
            for pat in tab_patterns:
                for match in pat.finditer(content):
                    raw = match.group(1).strip()
                    # Handle array-style matches like '"Active", "Completed"'
                    if ',' in raw and '"' in raw:
                        for item in re.findall(r'["\']([^"\']+)["\']', raw):
                            entry['tabs'].add(item.strip())
                    else:
                        entry['tabs'].add(raw)

            # --- Button Discovery ---
            for match in button_pattern.finditer(content):
                label = match.group(1).strip()
                # Filter out JSX expressions and very short noise
                if not label.startswith('{') and len(label) > 1 and not label.startswith('//'):
                    entry['buttons'].add(label)

            # --- Modal / Drawer triggers ---
            for match in onclick_modal_pattern.finditer(content):
                modal_name = match.group(1).strip()
                entry['modals'].add(modal_name)

            # --- Form Field Discovery ---
            for pat in form_field_patterns:
                for match in pat.finditer(content):
                    field = match.group(1).strip()
                    if len(field) > 1:
                        entry['fields'].add(field)

    # Build the output string
    action_map = '\n\n=== UI ACTION MAP (Component Auditor) ===\n'
    action_map += 'This map was auto-generated by scanning JSX/TSX components.\n'
    action_map += 'Use this as the SOURCE OF TRUTH for UI elements.\n\n'

    if not pages:
        action_map += '(No page-level components detected)\n'
        print('DEBUG: Component Auditor found 0 pages.')
        return action_map

    for page_name, data in sorted(pages.items()):
        action_map += f'## Page: {page_name}\n'
        action_map += f'  Visible Tabs: {sorted(data["tabs"]) if data["tabs"] else "[None detected]"}\n'
        action_map += f'  Primary Actions (Buttons): {sorted(data["buttons"]) if data["buttons"] else "[None detected]"}\n'
        action_map += f'  Modal/Drawer Triggers: {sorted(data["modals"]) if data["modals"] else "[None detected]"}\n'
        action_map += f'  Form Fields: {sorted(data["fields"]) if data["fields"] else "[None detected]"}\n\n'

    action_map += '=== END UI ACTION MAP ===\n'

    print(f'DEBUG: Component Auditor mapped {len(pages)} pages.')
    for pn in sorted(pages.keys()):
        d = pages[pn]
        print(f'  [{pn}] tabs={len(d["tabs"])} buttons={len(d["buttons"])} modals={len(d["modals"])} fields={len(d["fields"])}')

    return action_map


def _discover_project_identity(repo_dir: str) -> dict:
    """Identity & URL Discovery Agent.

    Recursively probes the repo to determine:
    - Project type (Public Website vs Admin Portal vs Hybrid)
    - Base URL for local development
    - All application routes (React Router, Next.js file-system, Vue Router, etc.)
    - Auth/login form schema metadata (Zod, Yup, HTML)
    - Tech stack versions from package.json
    - Environment variable keys

    Returns a structured dict.
    """
    print('DEBUG: Starting Identity & URL Discovery Agent...')

    result = {
        'project_type': 'UNKNOWN',
        'base_url': 'http://localhost:3000',
        'routes': [],
        'login_metadata': {},
        'env_keys': [],
        'tech_stack': {},
    }

    junk_dirs = {'node_modules', '.git', 'dist', 'build', 'coverage', '.next', 'public', 'assets'}

    # ── 1. Identity Markers ──────────────────────────────────────────────
    has_seo = False
    has_auth = False

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in junk_dirs]
        for f in files:
            fl = f.lower()
            if fl in ('robots.txt', 'sitemap.xml', 'next-sitemap.config.js',
                      'next-sitemap.config.mjs', 'next-seo.config.js'):
                has_seo = True
            if any(k in fl for k in ('login', 'signin', 'auth', 'signup', 'register')):
                has_auth = True

    if has_seo and has_auth:
        result['project_type'] = 'HYBRID_PLATFORM'
    elif has_seo:
        result['project_type'] = 'PUBLIC_WEBSITE'
    elif has_auth:
        result['project_type'] = 'ADMIN_PORTAL'

    print(f"  Identity: {result['project_type']} (SEO={has_seo}, Auth={has_auth})")

    # ── 2. Base URL Discovery ────────────────────────────────────────────
    env_files = ['.env', '.env.local', '.env.development', '.env.example']
    url_re = re.compile(
        r'(?:VITE_|NEXT_PUBLIC_|REACT_APP_)?(?:API_URL|BASE_URL|APP_URL|SITE_URL)'
        r'\s*=\s*["\']?([^\s"\']+)',
        re.IGNORECASE,
    )
    port_re = re.compile(r'(?:PORT|DEV_PORT)\s*=\s*["\']?(\d+)', re.IGNORECASE)

    for env_file in env_files:
        env_path = os.path.join(repo_dir, env_file)
        if not os.path.exists(env_path):
            continue
        try:
            with open(env_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            for line in content.split('\n'):
                if '=' in line and not line.strip().startswith('#'):
                    key = line.split('=')[0].strip()
                    if key:
                        result['env_keys'].append(key)
            for m in url_re.finditer(content):
                result['base_url'] = m.group(1)
            for m in port_re.finditer(content):
                result['base_url'] = f'http://localhost:{m.group(1)}'
        except Exception:
            pass

    # package.json → tech stack + port from scripts
    pkg_path = os.path.join(repo_dir, 'package.json')
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, 'r', encoding='utf-8', errors='ignore') as f:
                pkg = json.loads(f.read())
            deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
            for key in [
                'react', 'vue', 'angular', 'next', 'nuxt', 'vite',
                'redux', '@reduxjs/toolkit', 'zustand', 'mobx',
                'socket.io-client', 'axios', 'tailwindcss', 'express',
            ]:
                if key in deps:
                    result['tech_stack'][key] = deps[key]
            dev_script = pkg.get('scripts', {}).get('dev', '') or pkg.get('scripts', {}).get('start', '')
            pm = re.search(r'--port\s+(\d+)|-p\s+(\d+)', dev_script)
            if pm:
                port = pm.group(1) or pm.group(2)
                result['base_url'] = f'http://localhost:{port}'
        except Exception:
            pass

    # vite.config → port
    for cfg in ('vite.config.ts', 'vite.config.js', 'vite.config.mjs'):
        cfg_path = os.path.join(repo_dir, cfg)
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                pm = re.search(r'port\s*:\s*(\d+)', content)
                if pm:
                    result['base_url'] = f'http://localhost:{pm.group(1)}'
            except Exception:
                pass
            break

    print(f"  Base URL: {result['base_url']}")
    print(f"  Tech Stack: {result['tech_stack']}")
    print(f"  Env Keys: {len(result['env_keys'])} found")

    # ── 3. Recursive Route Discovery ─────────────────────────────────────
    route_patterns = [
        # React Router: <Route path="/trips" ... />
        re.compile(r'<Route[^>]*path\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
        # Route config objects: { path: "/trips", ... }
        re.compile(r'path\s*:\s*["\'](\/[^"\']*)["\']'),
        # Backend routes: app.get('/api/trips')
        re.compile(
            r'(?:app|router)\s*\.\s*(?:get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        ),
    ]

    discovered_routes: set[str] = set()

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in junk_dirs]
        for fname in files:
            if not fname.endswith(('.tsx', '.ts', '.jsx', '.js', '.vue', '.py')):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                for pat in route_patterns:
                    for m in pat.finditer(content):
                        route = m.group(1)
                        if route and not route.startswith('http') and len(route) < 100:
                            discovered_routes.add(route)
            except Exception:
                pass

    # Next.js / Nuxt.js file-based routing
    for pages_root in [
        os.path.join(repo_dir, 'app'),
        os.path.join(repo_dir, 'pages'),
        os.path.join(repo_dir, 'src', 'app'),
        os.path.join(repo_dir, 'src', 'pages'),
    ]:
        if not os.path.isdir(pages_root):
            continue
        for root, dirs, files in os.walk(pages_root):
            dirs[:] = [d for d in dirs if not d.startswith('_') and d not in junk_dirs]
            rel = os.path.relpath(root, pages_root)
            route_base = '/' if rel == '.' else '/' + rel.replace('\\', '/').replace('[', ':').replace(']', '')
            for f in files:
                if f in ('page.tsx', 'page.ts', 'page.jsx', 'page.js',
                         'index.tsx', 'index.ts', 'index.jsx', 'index.js'):
                    discovered_routes.add(route_base)
                elif f.endswith(('.tsx', '.ts', '.jsx', '.js')) and not f.startswith('_'):
                    name = os.path.splitext(f)[0]
                    if name not in ('layout', 'loading', 'error', 'not-found', 'template'):
                        page_route = route_base.rstrip('/') + '/' + name if route_base != '/' else '/' + name
                        discovered_routes.add(page_route)

    result['routes'] = sorted(discovered_routes)
    print(f"  Routes: {len(result['routes'])} discovered")
    for r in result['routes'][:10]:
        print(f"    {r}")
    if len(result['routes']) > 10:
        print(f"    ... and {len(result['routes']) - 10} more")

    # ── 4. Auth Schema Extraction ────────────────────────────────────────
    auth_files = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in junk_dirs]
        for f in files:
            if any(k in f.lower() for k in ('login', 'signin', 'auth', 'signup', 'register')):
                if f.endswith(('.tsx', '.ts', '.jsx', '.js', '.vue')):
                    auth_files.append(os.path.join(root, f))

    if auth_files:
        login_fields: set[str] = set()
        login_selectors: dict = {}  # CSS selectors for automated login
        validation_lib = 'none'

        for af in auth_files:
            try:
                with open(af, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if 'zod' in content.lower() or 'z.object' in content:
                    validation_lib = 'zod'
                elif 'yup' in content.lower() or 'yup.object' in content:
                    validation_lib = 'yup'
                field_patterns = [
                    re.compile(r'(?:name|id)\s*=\s*["\']([\w]+)["\']'),
                    re.compile(r'(\w+)\s*:\s*z\.(?:string|number|email|boolean)'),
                    re.compile(r'(\w+)\s*:\s*yup\.(?:string|number|email|boolean)'),
                ]
                skip_names = {'div', 'form', 'button', 'submit', 'type', 'class', 'style',
                              'input', 'span', 'label', 'section', 'main', 'header'}
                for pat in field_patterns:
                    for m in pat.finditer(content):
                        field = m.group(1)
                        if field.lower() not in skip_names:
                            login_fields.add(field)

                # --- Login Selector Extraction ---
                # Find input elements with id/name for username/email/password
                input_selector_re = re.compile(
                    r'<(?:input|Input|TextField|TextInput)[^>]*'
                    r'(?:id|name)\s*=\s*["\']([\w-]+)["\']'
                    r'[^>]*(?:type\s*=\s*["\']([\w]+)["\'])?',
                    re.IGNORECASE,
                )
                for m in input_selector_re.finditer(content):
                    field_id = m.group(1)
                    field_type = (m.group(2) or '').lower()
                    fid_lower = field_id.lower()
                    # Identify username/email selector
                    if any(k in fid_lower for k in ('email', 'username', 'user', 'login')):
                        login_selectors['username_selector'] = f'#{field_id}'
                        login_selectors['username_field'] = field_id
                    # Identify password selector
                    elif field_type == 'password' or 'password' in fid_lower or 'pass' in fid_lower:
                        login_selectors['password_selector'] = f'#{field_id}'
                        login_selectors['password_field'] = field_id

                # Also try name-based selectors: name="email", name="password"
                name_re = re.compile(r'name\s*=\s*["\']([\w-]+)["\']', re.IGNORECASE)
                for m in name_re.finditer(content):
                    name_val = m.group(1).lower()
                    if any(k in name_val for k in ('email', 'username', 'user', 'login')):
                        if 'username_selector' not in login_selectors:
                            login_selectors['username_selector'] = f'[name="{m.group(1)}"]'
                            login_selectors['username_field'] = m.group(1)
                    elif 'password' in name_val or 'pass' in name_val:
                        if 'password_selector' not in login_selectors:
                            login_selectors['password_selector'] = f'[name="{m.group(1)}"]'
                            login_selectors['password_field'] = m.group(1)

                # Detect submit button selector
                submit_re = re.compile(
                    r'<(?:button|Button)[^>]*type\s*=\s*["\']submit["\'][^>]*>'
                    r'\s*([^<]{1,30})\s*</(?:button|Button)>',
                    re.IGNORECASE,
                )
                for m in submit_re.finditer(content):
                    login_selectors['submit_text'] = m.group(1).strip()

            except Exception:
                pass

        result['login_metadata'] = {
            'auth_files': [os.path.relpath(af, repo_dir) for af in auth_files],
            'fields': sorted(login_fields),
            'validation_library': validation_lib,
            'login_selectors': login_selectors,
        }
        print(f"  Auth: {len(auth_files)} files, {len(login_fields)} fields, validation={validation_lib}")
        if login_selectors:
            print(f"  Login Selectors: {login_selectors}")

    print('DEBUG: Identity & URL Discovery complete.')
    return result


class WebsiteReader:
    """Playwright-based Website Reader for capturing live application state.

    Handles the full lifecycle: dev server → login → crawl → extract → save.
    Gracefully falls back if Playwright is not installed or the server won't start.
    """

    def __init__(
        self,
        repo_dir: str,
        base_url: str,
        routes: list,
        login_selectors: dict | None = None,
    ):
        self.repo_dir = repo_dir
        self.base_url = base_url
        self.routes = routes
        self.login_selectors = login_selectors or {}
        self.dev_server_proc = None
        self.scrape_url = ''
        self.state: dict = {
            'status': 'pending',
            'base_url': base_url,
            'authenticated': False,
            'pages': [],
        }

    async def start_dev_server(self) -> bool:
        """Install deps, start dev server, wait for readiness. Returns True if ready."""
        # 1. Install dependencies
        print('[WebsiteReader] Installing npm dependencies...')
        try:
            install_result = subprocess.run(
                ['npm', 'install', '--legacy-peer-deps'],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if install_result.returncode != 0:
                print(f'[WebsiteReader] npm install warning: {install_result.stderr[:300]}')
        except Exception as e:
            print(f'[WebsiteReader] npm install failed: {e}')
            return False

        # 2. Start dev server
        print('[WebsiteReader] Starting dev server...')
        self.dev_server_proc = subprocess.Popen(
            ['npm', 'run', 'dev'],
            cwd=self.repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, 'PORT': '4173', 'BROWSER': 'none'},
        )

        # 3. Resolve the scrape URL (force port 4173)
        self.scrape_url = self.base_url.rstrip('/')
        if ':3000' in self.scrape_url or ':5173' in self.scrape_url:
            self.scrape_url = re.sub(r':\d+', ':4173', self.scrape_url)
        elif ':' not in self.scrape_url.split('//')[-1]:
            self.scrape_url = self.scrape_url + ':4173'

        # 4. Wait for readiness (up to 60s)
        for _ in range(30):
            await asyncio.sleep(2)
            try:
                urllib.request.urlopen(self.scrape_url, timeout=3)
                print(f'[WebsiteReader] Dev server ready at {self.scrape_url}')
                return True
            except Exception:
                pass

        print('[WebsiteReader] Dev server failed to start within 60s.')
        return False

    async def login(self, page) -> bool:
        """Attempt role-based automated login using discovered selectors.

        Supports role-based credentials via environment variables:
        - BROKER_EMAIL / BROKER_PASSWORD for Broker role
        - ADMIN_EMAIL / ADMIN_PASSWORD for Admin role
        - Falls back to TEST_LOGIN_EMAIL / TEST_LOGIN_PASSWORD
        Returns True if a post-login navigation occurs.
        """
        if not self.login_selectors:
            print('[WebsiteReader] No login selectors found. Skipping login.')
            return False

        username_sel = self.login_selectors.get('username_selector')
        password_sel = self.login_selectors.get('password_selector')

        if not username_sel or not password_sel:
            print('[WebsiteReader] Incomplete login selectors. Skipping login.')
            return False

        try:
            # Navigate to login page
            login_routes = [r for r in self.routes if any(k in r.lower() for k in ('login', 'signin', 'auth'))]
            login_url = f'{self.scrape_url}{login_routes[0]}' if login_routes else self.scrape_url

            print(f'[WebsiteReader] Navigating to login: {login_url}')
            await page.goto(login_url, wait_until='networkidle', timeout=15000)
            await page.wait_for_timeout(1000)

            # Role-based credential resolution
            # Priority: Broker → Admin → Test → Default
            login_email = (
                os.getenv('BROKER_EMAIL')
                or os.getenv('ADMIN_EMAIL')
                or os.getenv('TEST_LOGIN_EMAIL')
                or 'test@test.com'
            )
            login_pass = (
                os.getenv('BROKER_PASSWORD')
                or os.getenv('ADMIN_PASSWORD')
                or os.getenv('TEST_LOGIN_PASSWORD')
                or 'password123'
            )
            active_role = 'Broker' if os.getenv('BROKER_EMAIL') else 'Admin' if os.getenv('ADMIN_EMAIL') else 'Test'

            print(f'[WebsiteReader] Logging in as {active_role} ({login_email})...')
            await page.fill(username_sel, login_email)
            await page.fill(password_sel, login_pass)

            # Click submit
            submit_text = self.login_selectors.get('submit_text', 'Login')
            try:
                submit_btn = page.get_by_role('button', name=re.compile(submit_text, re.IGNORECASE))
                await submit_btn.click()
            except Exception:
                await page.click('button[type="submit"]')

            # Wait for navigation
            await page.wait_for_load_state('networkidle', timeout=10000)
            await page.wait_for_timeout(2000)

            # Check if we left the login page
            current_url = page.url
            if any(k in current_url.lower() for k in ('dashboard', 'home', 'admin', 'main', 'trips')):
                print(f'[WebsiteReader] ✓ Login successful as {active_role}. Redirected to: {current_url}')
                self.state['authenticated'] = True
                self.state['login_role'] = active_role
                return True
            else:
                print(f'[WebsiteReader] Login attempt completed. Current URL: {current_url}')
                return False

        except Exception as e:
            print(f'[WebsiteReader] Login failed: {str(e)[:200]}')
            return False

    async def extract_page_state(self, page, route_path: str) -> dict:
        """Extract all interactive UI elements, then PROBE tabs and buttons."""
        url = f'{self.scrape_url}{route_path}'
        print(f'[WebsiteReader] → {url}')

        await page.goto(url, wait_until='networkidle', timeout=15000)
        await page.wait_for_timeout(1000)

        page_data: dict = {
            'route': route_path,
            'url': url,
            'title': await page.title(),
            'layout_description': '',
            'headings': [],
            'tabs': [],
            'tab_states': [],        # NEW: probed tab content
            'buttons': [],
            'modal_triggers': [],
            'sub_features': [],      # NEW: probed button/modal content
            'form_fields': [],
            'links': [],
            'content_markdown': '',
        }

        # --- Headings ---
        headings = await page.query_selector_all('h1, h2, h3')
        for h in headings[:10]:
            text = await h.text_content()
            tag = await h.evaluate('el => el.tagName')
            if text and text.strip():
                page_data['headings'].append({'tag': tag, 'text': text.strip()})

        # --- Tabs (accessibility-based: active vs inactive) ---
        tabs = await page.get_by_role('tab').all()
        for tab in tabs:
            text = await tab.text_content()
            is_selected = await tab.get_attribute('aria-selected')
            if text and text.strip():
                page_data['tabs'].append({
                    'label': text.strip(),
                    'active': is_selected == 'true',
                })

        # --- Buttons (with action detection) ---
        buttons = await page.get_by_role('button').all()
        for btn in buttons[:30]:
            text = await btn.text_content()
            if text and text.strip() and 1 < len(text.strip()) < 60:
                btn_label = text.strip()
                page_data['buttons'].append(btn_label)

                onclick = await btn.get_attribute('onclick') or ''
                aria_haspopup = await btn.get_attribute('aria-haspopup') or ''
                data_target = await btn.get_attribute('data-target') or ''
                if aria_haspopup in ('dialog', 'true') or data_target or \
                   any(k in onclick.lower() for k in ('modal', 'dialog', 'drawer', 'open', 'show')):
                    page_data['modal_triggers'].append({
                        'button': btn_label,
                        'type': 'modal/dialog',
                    })

        # --- Form fields ---
        inputs = await page.query_selector_all('input, select, textarea')
        for inp in inputs[:30]:
            info = await inp.evaluate('''el => ({
                type: el.type || el.tagName.toLowerCase(),
                name: el.name || '',
                placeholder: el.placeholder || '',
                label: el.labels?.[0]?.textContent?.trim() || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                required: el.required || false,
            })''')
            identifier = (
                info.get('label')
                or info.get('placeholder')
                or info.get('ariaLabel')
                or info.get('name')
            )
            if identifier:
                page_data['form_fields'].append({
                    'type': info.get('type', 'text'),
                    'identifier': identifier,
                    'required': info.get('required', False),
                })

        # --- Navigation links ---
        links = await page.query_selector_all('nav a, [role="navigation"] a, aside a')
        for link in links[:20]:
            text = await link.text_content()
            href = await link.get_attribute('href')
            if text and text.strip():
                page_data['links'].append({'text': text.strip(), 'href': href or ''})

        # ═══════════════════════════════════════════════════════════
        # PROBING PHASE: Click tabs and buttons to reveal hidden UI
        # ═══════════════════════════════════════════════════════════
        if page_data['tabs']:
            print(f'[WebsiteReader]   Probing {len(page_data["tabs"])} tabs...')
            page_data['tab_states'] = await self._probe_tabs(page)

        if page_data['buttons']:
            print(f'[WebsiteReader]   Probing buttons for modals...')
            page_data['sub_features'] = await self._probe_buttons(page)

        # --- Layout Description (auto-generated from probed data) ---
        sections = []
        if page_data['headings']:
            h1s = [h['text'] for h in page_data['headings'] if h['tag'] == 'H1']
            if h1s:
                sections.append(f'Page titled "{h1s[0]}"')
        if page_data['tab_states']:
            tab_labels = [t['label'] for t in page_data['tab_states'] if 'label' in t]
            sections.append(f'{len(tab_labels)}-tab navigation: {tab_labels}')
        elif page_data['tabs']:
            all_tabs = [t['label'] for t in page_data['tabs']]
            sections.append(f'Tab bar with {len(all_tabs)} tabs: {all_tabs}')
        if page_data['sub_features']:
            sections.append(f'{len(page_data["sub_features"])} modals/drawers discovered')
        if page_data['buttons']:
            sections.append(f'{len(page_data["buttons"])} action buttons visible')
        if page_data['form_fields']:
            sections.append(f'Form with {len(page_data["form_fields"])} input fields')
        page_data['layout_description'] = '. '.join(sections) + '.' if sections else 'Minimal page content.'

        # --- Markdown Transformation ---
        try:
            page_data['content_markdown'] = await page.evaluate('''() => {
                const body = document.body;
                let md = '';
                const walk = (el) => {
                    if (!el || el.nodeType !== 1) return;
                    const tag = el.tagName;
                    const text = el.textContent?.trim() || '';
                    if (!text || text.length > 500) return;
                    if (tag === 'H1') md += '# ' + text + '\\n';
                    else if (tag === 'H2') md += '## ' + text + '\\n';
                    else if (tag === 'H3') md += '### ' + text + '\\n';
                    else if (tag === 'P' && text.length > 10) md += text + '\\n';
                    else if (tag === 'BUTTON') md += '- [Button] ' + text + '\\n';
                    else if (tag === 'A' && el.href) md += '- [Link] ' + text + '\\n';
                    else if (tag === 'TH') md += '| ' + text + ' ';
                    else {
                        for (const child of el.children) walk(child);
                    }
                };
                walk(body);
                return md.substring(0, 3000);
            }''')
        except Exception:
            page_data['content_markdown'] = ''

        print(
            f'[WebsiteReader] ✓ {route_path}: '
            f'{len(page_data["tabs"])} tabs, '
            f'{len(page_data["tab_states"])} probed, '
            f'{len(page_data["buttons"])} buttons, '
            f'{len(page_data["sub_features"])} sub-features'
        )
        return page_data

    async def _probe_tabs(self, page) -> list:
        """Click each tab and capture the unique content revealed.

        For each tab:
        - Click it and wait for networkidle
        - Extract table column headers (TH elements)
        - Count data rows
        - Capture action buttons visible in THIS tab state
        - Build instruction synthesis text
        """
        tab_states = []
        tabs = await page.get_by_role('tab').all()

        for tab in tabs:
            text = await tab.text_content()
            if not text or not text.strip():
                continue
            label = text.strip()

            try:
                # Click the tab
                await tab.click()
                await page.wait_for_load_state('networkidle', timeout=8000)
                await page.wait_for_timeout(800)

                # Extract table headers visible now
                headers = []
                ths = await page.query_selector_all('th')
                for th in ths[:20]:
                    th_text = await th.text_content()
                    if th_text and th_text.strip() and len(th_text.strip()) < 80:
                        headers.append(th_text.strip())

                # Count data rows
                rows = await page.query_selector_all('tbody tr')
                row_count = len(rows)

                # Capture buttons visible in this tab state
                tab_buttons = []
                btns = await page.get_by_role('button').all()
                for btn in btns[:20]:
                    btn_text = await btn.text_content()
                    if btn_text and btn_text.strip() and 1 < len(btn_text.strip()) < 60:
                        tab_buttons.append(btn_text.strip())

                # Build instruction synthesis
                synthesis = f'When the user clicks the "{label}" tab, the system displays '
                if headers:
                    synthesis += f'a table with columns: {headers}. '
                if row_count > 0:
                    synthesis += f'{row_count} rows of data are shown. '
                if tab_buttons:
                    synthesis += f'Available actions: {tab_buttons}.'

                tab_states.append({
                    'label': label,
                    'table_headers': headers,
                    'row_count': row_count,
                    'action_buttons': tab_buttons,
                    'instruction_synthesis': synthesis,
                })

                print(f'[WebsiteReader]     Tab "{label}": {len(headers)} columns, {row_count} rows, {len(tab_buttons)} buttons')

            except Exception as e:
                print(f'[WebsiteReader]     Tab "{label}" probe failed: {str(e)[:100]}')
                tab_states.append({'label': label, 'error': str(e)[:100]})

        return tab_states

    async def _probe_buttons(self, page) -> list:
        """Click each button and detect if it opens a modal/drawer.

        For each newly-appeared modal:
        - Extract the modal title
        - Extract all form fields inside the modal
        - Extract action buttons in the modal
        - Close the modal (Escape or close button)
        - Build instruction synthesis text
        """
        sub_features = []
        skip_labels = {'close', 'cancel', 'back', 'x', '×', 'dismiss', 'ok', 'no', 'yes'}

        buttons = await page.get_by_role('button').all()

        for btn in buttons[:20]:
            text = await btn.text_content()
            if not text or not text.strip() or len(text.strip()) > 50:
                continue
            label = text.strip()
            if label.lower() in skip_labels:
                continue

            try:
                is_visible = await btn.is_visible()
                if not is_visible:
                    continue

                # Snapshot: count dialogs before click
                modal_selectors = '[role="dialog"], .modal, .MuiDialog-root, .ant-modal, .drawer, [role="presentation"], .ant-drawer'
                before_count = len(await page.query_selector_all(modal_selectors))

                await btn.click()
                await page.wait_for_timeout(1200)

                # Check if a new modal/drawer appeared
                after_modals = await page.query_selector_all(modal_selectors)

                if len(after_modals) > before_count:
                    modal = after_modals[-1]  # The newly-opened one

                    # Extract modal title
                    modal_title = ''
                    title_el = await modal.query_selector('h1, h2, h3, [class*="title"], [class*="Title"], [class*="header"] > span')
                    if title_el:
                        modal_title = (await title_el.text_content() or '').strip()

                    # Extract modal form fields
                    modal_fields = []
                    inputs = await modal.query_selector_all('input, select, textarea')
                    for inp in inputs[:20]:
                        info = await inp.evaluate('''el => ({
                            type: el.type || el.tagName.toLowerCase(),
                            placeholder: el.placeholder || '',
                            label: el.labels?.[0]?.textContent?.trim() || '',
                            name: el.name || '',
                            required: el.required || false,
                        })''')
                        identifier = info.get('label') or info.get('placeholder') or info.get('name')
                        if identifier:
                            modal_fields.append({
                                'type': info.get('type', 'text'),
                                'identifier': identifier,
                                'required': info.get('required', False),
                            })

                    # Extract modal buttons
                    modal_buttons = []
                    modal_btns = await modal.query_selector_all('button')
                    for mb in modal_btns[:8]:
                        mb_text = await mb.text_content()
                        if mb_text and mb_text.strip() and len(mb_text.strip()) < 40:
                            modal_buttons.append(mb_text.strip())

                    # Build instruction synthesis
                    synthesis = f'When the user clicks "{label}", '
                    if modal_title:
                        synthesis += f'a modal titled "{modal_title}" appears. '
                    else:
                        synthesis += 'a modal/drawer appears. '
                    if modal_fields:
                        field_names = [f['identifier'] for f in modal_fields]
                        synthesis += f'It contains the following fields: {field_names}. '
                    if modal_buttons:
                        synthesis += f'The user can then click: {modal_buttons}.'

                    sub_features.append({
                        'trigger_button': label,
                        'type': 'modal',
                        'title': modal_title,
                        'form_fields': modal_fields,
                        'buttons': modal_buttons,
                        'instruction_synthesis': synthesis,
                    })

                    print(f'[WebsiteReader]     Modal "{modal_title or label}": {len(modal_fields)} fields, {len(modal_buttons)} buttons')

                    # Close the modal
                    try:
                        close_btn = await modal.query_selector(
                            '[aria-label="close"], [aria-label="Close"], '
                            'button:has-text("Close"), button:has-text("Cancel"), '
                            'button:has-text("×"), .ant-modal-close, .MuiIconButton-root'
                        )
                        if close_btn:
                            await close_btn.click()
                        else:
                            await page.keyboard.press('Escape')
                    except Exception:
                        await page.keyboard.press('Escape')
                    await page.wait_for_timeout(500)

            except Exception:
                pass  # Button didn't trigger a modal, skip silently

        return sub_features

    async def crawl(self) -> dict:
        """Full crawl pipeline: start server → login → visit all routes → extract state."""
        if not HAS_PLAYWRIGHT:
            print('[WebsiteReader] Playwright not installed. Skipping.')
            self.state['status'] = 'skipped'
            self.state['reason'] = 'playwright not installed'
            return self.state

        try:
            # Start dev server
            server_ok = await self.start_dev_server()
            if not server_ok:
                self.state['status'] = 'failed'
                self.state['reason'] = 'Dev server did not start'
                return self.state

            # Launch browser
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 720},
                )

                # Block heavy resources
                await context.route(
                    re.compile(r'\.(png|jpg|jpeg|gif|svg|woff|woff2|ttf|eot|ico|mp4|webm)$'),
                    lambda route: route.abort(),
                )

                page = await context.new_page()

                # Attempt login
                if self.login_selectors:
                    await self.login(page)

                # Crawl routes (limit to 20)
                routes_to_crawl = list(self.routes[:20])
                if '/' not in routes_to_crawl:
                    routes_to_crawl.insert(0, '/')

                for route_path in routes_to_crawl:
                    try:
                        page_state = await self.extract_page_state(page, route_path)
                        self.state['pages'].append(page_state)
                    except Exception as e:
                        print(f'[WebsiteReader] ✗ {route_path}: {str(e)[:120]}')
                        self.state['pages'].append({'route': route_path, 'error': str(e)[:200]})

                await browser.close()

            self.state['status'] = 'completed'
            print(f'[WebsiteReader] Crawl complete. {len(self.state["pages"])} pages captured.')

        except Exception as e:
            print(f'[WebsiteReader] Fatal error: {str(e)[:300]}')
            self.state['status'] = 'failed'
            self.state['reason'] = str(e)[:300]

        return self.state

    def save_state(self, output_dir: str) -> str:
        """Save the live app state to live_app_state.json for debugging."""
        output_path = os.path.join(output_dir, 'live_app_state.json')
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, default=str)
            print(f'[WebsiteReader] State saved to {output_path}')
        except Exception as e:
            print(f'[WebsiteReader] Failed to save state: {e}')
            output_path = ''
        return output_path

    async def cleanup(self):
        """Terminate the dev server process."""
        if self.dev_server_proc:
            try:
                self.dev_server_proc.terminate()
                self.dev_server_proc.wait(timeout=5)
            except Exception:
                try:
                    self.dev_server_proc.kill()
                except Exception:
                    pass
            print('[WebsiteReader] Dev server terminated.')
            self.dev_server_proc = None


def _trace_data_flow(repo_dir: str) -> str:
    """Trace onSubmit/handleSubmit events to their API endpoints.

    Scans source code for form submission handlers and maps them to the
    API calls they make. This reveals the 'Background Process' for
    non-technical users: what happens when they click Submit.

    Returns a formatted string for injection into the Gemini context.
    """
    junk_dirs = {'node_modules', '.git', 'dist', 'build', 'coverage', '.next', 'public', 'assets'}

    # Pattern 1: onSubmit={handleSomething} or onSubmit={(...) => ...}
    submit_handler_re = re.compile(
        r'on[Ss]ubmit\s*=\s*\{\s*([\w]+)',
        re.IGNORECASE,
    )
    # Pattern 2: const handleSomething = ... followed by fetch/axios/api call
    handler_body_re = re.compile(
        r'(?:const|function|async\s+function)\s+(handle\w*[Ss]ubmit\w*|on\w*[Ss]ubmit\w*)'
        r'[^}]*?(?:'
        r'(?:fetch|axios|api|service)\s*[\.\(]\s*[\`"\'](/?[\w/\-:{}]+)[\`"\']'
        r'|'
        r'(?:\.post|\.put|\.patch|\.delete|\.get)\s*\(\s*[\`"\'](/?[\w/\-:{}]+)[\`"\']'
        r')',
        re.DOTALL | re.IGNORECASE,
    )
    # Pattern 3: Direct API calls with method
    api_call_re = re.compile(
        r'(?:axios|fetch|api|http|request|service\w*)\s*\.(post|put|patch|delete|get)\s*\(\s*[\`"\'](/?[\w/\-:{}.$]+)[\`"\']',
        re.IGNORECASE,
    )

    data_flows: list[dict] = []
    seen_apis: set[str] = set()

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in junk_dirs]
        for fname in files:
            if not fname.endswith(('.tsx', '.ts', '.jsx', '.js')):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # Find submit handlers
                handler_names = set()
                for m in submit_handler_re.finditer(content):
                    handler_names.add(m.group(1))

                # Find API calls within handler bodies or anywhere in the file
                rel_path = os.path.relpath(fpath, repo_dir)
                for m in handler_body_re.finditer(content):
                    handler = m.group(1)
                    endpoint = m.group(2) or m.group(3)
                    if endpoint and endpoint not in seen_apis:
                        seen_apis.add(endpoint)
                        data_flows.append({
                            'file': rel_path,
                            'handler': handler,
                            'method': 'POST',
                            'endpoint': endpoint,
                        })

                for m in api_call_re.finditer(content):
                    method = m.group(1).upper()
                    endpoint = m.group(2)
                    if endpoint and endpoint not in seen_apis and not endpoint.startswith('http'):
                        seen_apis.add(endpoint)
                        # Try to find which handler calls this
                        handler = 'unknown'
                        for hn in handler_names:
                            if hn in content[:content.find(endpoint)]:
                                handler = hn
                                break
                        data_flows.append({
                            'file': rel_path,
                            'handler': handler,
                            'method': method,
                            'endpoint': endpoint,
                        })

            except Exception:
                pass

    if not data_flows:
        return ''

    output = '\n\n=== DATA FLOW TRACES (Form Submission → API) ===\n'
    output += f'Total API endpoints traced: {len(data_flows)}\n\n'

    for df in data_flows:
        output += f'  • {df["file"]}:\n'
        output += f'    Handler: {df["handler"]}()\n'
        output += f'    API Call: {df["method"]} {df["endpoint"]}\n'
        output += f'    Background Process: When the user submits, data is sent via {df["method"]} to {df["endpoint"]}\n\n'

    output += '=== END DATA FLOW TRACES ===\n'

    print(f'DEBUG: Data Flow Tracer found {len(data_flows)} form→API mappings.')
    for df in data_flows:
        print(f'  {df["handler"]}() → {df["method"]} {df["endpoint"]} ({df["file"]})')

    return output


def _build_sidebar_structure(
    discovery: dict,
    features_detected: list,
    scraped_data: dict,
    repo_dir: str,
) -> dict:
    """Content Architect – Build a CONSOLIDATED sidebar_structure.json.

    HARD LIMIT: Exactly 5 top-level categories, max 15 total items.

    Categories:
    1. OVERVIEW: Platform identity, ecosystem, architecture, login
    2. USER_GUIDES: Operational walkthroughs for Brokers/Carriers
    3. MODULE_REFERENCE: Detailed feature breakdowns (1 per business module)
    4. ADMINISTRATION: Settings, user management, roles, permissions
    5. TECHNICAL_REFERENCE: Engineer’s Blueprint (auto-generated)

    CONSOLIDATION RULES:
    - Sub-components, hooks, and helpers are MERGED into parent modules.
    - Routes like /trips/:id, /trips/new, /trips/edit are merged into ‘Trips’.
    - Maximum 15 sidebar items total (prevents 492-section bloat).
    """
    routes = discovery.get('routes', [])
    project_type = discovery.get('project_type', 'UNKNOWN')

    # Persona detection keywords
    broker_keys = {'broker', 'bid', 'rate', 'customer', 'client', 'dispatch', 'contract', 'invoice'}
    carrier_keys = {'carrier', 'driver', 'truck', 'vehicle', 'fleet', 'delivery'}

    # Category classification keywords
    admin_keys = {'setting', 'role', 'permission', 'account', 'team', 'member',
                  'preference', 'notification', 'config', 'admin', 'organization'}
    overview_routes = {'/', '/dashboard', '/home', '/main', '/landing', '/index', '/overview'}

    # Module consolidation map: group related routes under ONE parent
    module_groups: dict[str, dict] = {}   # key = canonical module name
    admin_items: list[dict] = []

    junk_dirs = {'node_modules', '.git', 'dist', 'build', '.next', 'public', 'assets', 'coverage'}
    skip_patterns = ('login', 'signin', 'signup', 'register', 'auth', 'callback', '404', '500')

    def _detect_persona(name_lower: str) -> str:
        if any(k in name_lower for k in broker_keys):
            return 'Broker'
        if any(k in name_lower for k in carrier_keys):
            return 'Carrier'
        return 'Admin'

    def _canonical_name(route: str) -> str:
        """Extract the root business concept from a route.

        /trips/:id/edit  →  trips
        /trip-management  →  trip-management
        /settings/roles   →  settings
        """
        clean = route.strip('/').split('/')[0]  # Take ONLY the first path segment
        clean = re.sub(r'[^a-z0-9-]', '', clean.lower())
        return clean or 'home'

    def _title_from_name(name: str) -> str:
        return name.replace('-', ' ').replace('_', ' ').title()

    def _make_slug(name: str) -> str:
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        return f'/docs/{slug}' if slug else '/docs/unknown'

    def _normalize_name(name: str) -> str:
        """Normalize a canonical name for fuzzy dedup.

        Strips hyphens, removes common suffixes, and lowercases.
        collaborations → collaboration
        collabrations  → collabration   (typo, but close enough for substring match)
        allloads       → allload
        all-loads      → allload
        assetspage     → asset
        assets         → asset
        goreadytrucks  → goreadytruck
        go-ready-trucks→ goreadytruck
        phoneverification → phoneverif...
        phone-verification→ phoneverif...
        """
        n = name.lower().replace('-', '').replace('_', '')
        # Strip common suffixes (order matters: longest first)
        for suffix in ('management', 'page', 'list', 'view', 'detail', 'details'):
            if n.endswith(suffix) and len(n) > len(suffix) + 2:
                n = n[:-len(suffix)]
        # Strip trailing 's' for plurals (but not if too short)
        if n.endswith('s') and len(n) > 4:
            n = n[:-1]
        return n

    def _find_existing_group(canonical: str) -> str | None:
        """Check if canonical is a fuzzy duplicate of an existing group key.

        Returns the existing key if found, else None.
        """
        norm = _normalize_name(canonical)
        for existing_key in module_groups:
            existing_norm = _normalize_name(existing_key)
            # Exact normalized match
            if norm == existing_norm:
                return existing_key
            # Substring match (one contains the other, min length 4)
            if len(norm) >= 4 and len(existing_norm) >= 4:
                if norm in existing_norm or existing_norm in norm:
                    return existing_key
        return None

    # Phase 1: Group routes by canonical module name (with fuzzy dedup)
    for route in routes:
        route_lower = route.lower().strip('/')

        # Skip auth/error routes entirely
        if any(k in route_lower for k in skip_patterns):
            continue

        canonical = _canonical_name(route)

        # Is this an admin/settings route?
        if any(k in canonical for k in admin_keys):
            if canonical not in [a.get('_canonical') for a in admin_items]:
                admin_items.append({
                    'title': _title_from_name(canonical),
                    'slug': _make_slug(canonical),
                    'route': route,
                    'persona': 'Admin',
                    'description': f'{_title_from_name(canonical)} administration.',
                    '_canonical': canonical,
                })
            continue

        # Is this an overview route?
        if route in overview_routes or canonical in ('', 'dashboard', 'home', 'main'):
            continue  # Will be added as fixed "Platform Overview" item

        # Consolidate: merge sub-routes into parent module (with fuzzy dedup)
        existing_key = _find_existing_group(canonical) if canonical not in module_groups else canonical
        if existing_key:
            module_groups[existing_key]['routes'].append(route)
        else:
            module_groups[canonical] = {
                'title': _title_from_name(canonical),
                'slug': _make_slug(canonical),
                'routes': [route],
                'persona': _detect_persona(canonical),
                'description': f'{_title_from_name(canonical)} module.',
            }

    # Phase 2: Scan file system for modules not captured by routes (with fuzzy dedup)
    src_dir = os.path.join(repo_dir, 'src')
    skip_src_dirs = {'components', 'utils', 'hooks', 'lib', 'styles', 'common',
                     'shared', 'layouts', 'assets', 'types', 'interfaces',
                     'constants', 'helpers', 'context', 'providers', 'store'}
    if os.path.isdir(src_dir):
        for subdir in ['pages', 'views', 'modules', 'features']:
            sub_path = os.path.join(src_dir, subdir)
            if os.path.isdir(sub_path):
                for child in os.listdir(sub_path):
                    child_lower = child.lower()
                    if (os.path.isdir(os.path.join(sub_path, child))
                            and child_lower not in junk_dirs
                            and child_lower not in skip_src_dirs
                            and not any(k in child_lower for k in skip_patterns)):
                        # Check fuzzy dedup before adding
                        if child_lower not in module_groups and not _find_existing_group(child_lower):
                            module_groups[child_lower] = {
                                'title': _title_from_name(child_lower),
                                'slug': _make_slug(child_lower),
                                'routes': [f'/{child_lower}'],
                                'persona': _detect_persona(child_lower),
                                'description': f'{_title_from_name(child_lower)} module (from file structure).',
                            }

    # Phase 3: Enrich with probed data
    scraped_pages = scraped_data.get('pages', []) if scraped_data.get('status') == 'completed' else []
    for _, group in module_groups.items():
        for pg in scraped_pages:
            if pg.get('route') in group.get('routes', []):
                group['probed_tabs'] = len(pg.get('tab_states', []))
                group['probed_buttons'] = len(pg.get('buttons', []))
                group['probed_modals'] = len(pg.get('sub_features', []))
                break

    # Phase 4: Split modules into USER_GUIDES vs MODULE_REFERENCE
    # User-facing operational modules with tabs/tables = USER_GUIDES
    # Everything else = MODULE_REFERENCE
    user_guide_items = []
    module_ref_items = []

    for _, group in sorted(module_groups.items()):
        item = {
            'title': group['title'],
            'slug': group['slug'],
            'route': group['routes'][0] if group['routes'] else '',
            'persona': group['persona'],
            'description': group['description'],
        }
        if group.get('probed_tabs'):
            item['probed_tabs'] = group['probed_tabs']
            item['probed_buttons'] = group.get('probed_buttons', 0)
            item['probed_modals'] = group.get('probed_modals', 0)

        # Heuristic: if probed or has 'broker'/'carrier' persona, it's a user guide
        if group.get('probed_tabs') or group['persona'] in ('Broker', 'Carrier'):
            user_guide_items.append(item)
        else:
            module_ref_items.append(item)

    # Phase 5: Build the 5-category structure
    sidebar: dict = {
        'project_name': discovery.get('tech_stack', {}).get('name', 'Application'),
        'project_type': project_type,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'categories': [
            {
                'name': 'OVERVIEW',
                'icon': '🏠',
                'description': 'Platform identity, architecture, and getting started.',
                'items': [
                    {
                        'title': 'Platform Overview',
                        'slug': '/docs/platform-overview',
                        'route': '/',
                        'persona': 'All Users',
                        'description': 'Executive summary, system architecture, login flow, and user roles.',
                    },
                ],
            },
            {
                'name': 'USER_GUIDES',
                'icon': '📖',
                'description': 'Operational walkthroughs for Brokers and Carriers.',
                'items': user_guide_items,
            },
            {
                'name': 'MODULE_REFERENCE',
                'icon': '📦',
                'description': 'Detailed feature breakdowns for each business module.',
                'items': module_ref_items,
            },
            {
                'name': 'ADMINISTRATION',
                'icon': '⚙️',
                'description': 'Settings, user management, roles, and permissions.',
                'items': admin_items,
            },
            {
                'name': 'TECHNICAL_REFERENCE',
                'icon': '💻',
                'description': 'For developers only: tech stack, APIs, environment config.',
                'items': [
                    {
                        'title': "Engineer's Blueprint",
                        'slug': '/docs/engineer-blueprint',
                        'persona': 'Developer',
                        'description': 'Tech stack audit, auth flow, API map, env config, state management.',
                    },
                ],
            },
        ],
    }

    # Remove empty categories (but keep OVERVIEW and TECHNICAL_REFERENCE always)
    sidebar['categories'] = [
        c for c in sidebar['categories']
        if c['items'] or c['name'] in ('OVERVIEW', 'TECHNICAL_REFERENCE')
    ]

    total_items = sum(len(c['items']) for c in sidebar['categories'])
    print(f'DEBUG: Sidebar built – {len(sidebar["categories"])} categories, {total_items} total items (max 15).')
    for cat in sidebar['categories']:
        print(f'  {cat["icon"]} {cat["name"]}: {len(cat["items"])} items')
        for item in cat['items']:
            print(f'    → {item["slug"]}: {item["title"]} (Persona: {item.get("persona", "All")})')

    if total_items > 15:
        print(f'  ⚠️ WARNING: {total_items} items exceeds target of 15. Consider further consolidation.')

    return sidebar


def _format_sidebar_for_context(sidebar: dict) -> str:
    """Convert sidebar structure into context for Gemini.

    Includes consolidation and Mermaid safety reminders.
    """
    output = '\n\n=== SIDEBAR STRUCTURE MANIFEST (5 CATEGORIES – FOLLOW EXACTLY) ===\n'
    output += f'Project: {sidebar.get("project_name", "Unknown")}\n'
    output += f'Type: {sidebar.get("project_type", "UNKNOWN")}\n\n'

    output += '!! CRITICAL: Generate EXACTLY ONE `<!-- MODULE: slug -->` section for EACH item below. !!\n'
    output += '!! DO NOT create extra sections for individual components, hooks, or helpers. !!\n'
    output += '!! ALL Mermaid diagrams MUST use ["Label"] rectangles only. NO (()) or {{}} shapes. !!\n\n'

    for cat in sidebar.get('categories', []):
        output += f'\n## {cat["icon"]} {cat["name"]}: {cat.get("description", "")}\n'
        for item in cat['items']:
            output += f'  - slug: {item["slug"]}\n'
            output += f'    title: {item["title"]}\n'
            output += f'    persona: {item.get("persona", "All Users")}\n'
            output += f'    description: {item.get("description", "")}\n'
            if item.get('probed_tabs'):
                output += f'    probed: {item["probed_tabs"]} tabs, {item.get("probed_buttons", 0)} buttons, {item.get("probed_modals", 0)} modals\n'

    output += '\n=== END SIDEBAR MANIFEST ===\n'
    return output


def _split_docs_by_module(markdown_text: str, sidebar: dict) -> dict:
    """Split a single Gemini markdown output into per-module files.

    Looks for `<!-- MODULE: slug -->` markers and splits accordingly.
    Returns a dict of {slug: markdown_content}.
    """
    documentation: dict = {}

    # Collect all slugs for reference
    all_slugs = []
    for cat in sidebar.get('categories', []):
        for item in cat['items']:
            all_slugs.append(item['slug'])

    # Split by marker
    marker_pattern = re.compile(r'<!-- MODULE:\s*(/docs/[\w-]+)\s*-->')
    parts = marker_pattern.split(markdown_text)

    # parts will be: [preamble, slug1, content1, slug2, content2, ...]
    # Process in pairs
    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            slug = parts[i].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ''
            if slug and content:
                documentation[slug] = content

    # If splitting failed, put everything under platform-overview
    if not documentation and markdown_text.strip():
        documentation['/docs/platform-overview'] = markdown_text.strip()

    # Map slugs to filenames
    file_docs = {}
    for slug, content in documentation.items():
        filename = slug.replace('/docs/', '') + '.md'
        file_docs[filename] = content

    print(f'DEBUG: Split docs into {len(file_docs)} module files: {list(file_docs.keys())}')
    return file_docs


def _format_scrape_for_context(scraped_data: dict) -> str:
    """Convert probed live_app_state dict into a readable context string for Gemini."""
    if scraped_data.get('status') != 'completed' or not scraped_data.get('pages'):
        return ''

    output = '\n\n=== PROBED LIVE APP STATE (WebsiteReader – Interactive Crawl) ===\n'
    output += f'Base URL: {scraped_data.get("base_url", "unknown")}\n'
    output += f'Authenticated: {scraped_data.get("authenticated", False)}\n'
    output += f'Login Role: {scraped_data.get("login_role", "unknown")}\n'
    output += f'Pages captured: {len(scraped_data["pages"])}\n\n'

    for pg in scraped_data['pages']:
        if 'error' in pg:
            output += f'## Route: {pg["route"]} [SCRAPE FAILED]\n\n'
            continue

        output += f'## Route: {pg.get("route", "?")}\n'
        output += f'  Title: {pg.get("title", "")}\n'
        if pg.get('layout_description'):
            output += f'  Layout: {pg["layout_description"]}\n'

        if pg.get('headings'):
            output += f'  Headings: {[h["text"] for h in pg["headings"]]}\n'

        # --- Tab States (probed by clicking each tab) ---
        if pg.get('tab_states'):
            output += '  --- PROBED TAB STATES ---\n'
            for ts in pg['tab_states']:
                if 'error' in ts:
                    output += f'    Tab "{ts["label"]}": [PROBE FAILED]\n'
                    continue
                output += f'    Tab "{ts["label"]}":\n'
                if ts.get('table_headers'):
                    output += f'      Table Columns: {ts["table_headers"]}\n'
                output += f'      Data Rows: {ts.get("row_count", 0)}\n'
                if ts.get('action_buttons'):
                    output += f'      Action Buttons: {ts["action_buttons"]}\n'
                if ts.get('instruction_synthesis'):
                    output += f'      Synthesis: {ts["instruction_synthesis"]}\n'
        elif pg.get('tabs'):
            active = [t['label'] for t in pg['tabs'] if t.get('active')]
            inactive = [t['label'] for t in pg['tabs'] if not t.get('active')]
            output += f'  Active Tab: {active}\n'
            output += f'  Other Tabs: {inactive}\n'

        if pg.get('buttons'):
            output += f'  Buttons: {pg["buttons"]}\n'

        # --- Sub-Features (probed by clicking buttons) ---
        if pg.get('sub_features'):
            output += '  --- PROBED SUB-FEATURES (Modals/Drawers) ---\n'
            for sf in pg['sub_features']:
                output += f'    Trigger: "{sf["trigger_button"]}" button\n'
                if sf.get('title'):
                    output += f'      Modal Title: "{sf["title"]}"\n'
                if sf.get('form_fields'):
                    fields = [f'{f["identifier"]} ({f["type"]}){", required" if f.get("required") else ""}'
                              for f in sf['form_fields']]
                    output += f'      Modal Fields: {fields}\n'
                if sf.get('buttons'):
                    output += f'      Modal Buttons: {sf["buttons"]}\n'
                if sf.get('instruction_synthesis'):
                    output += f'      Synthesis: {sf["instruction_synthesis"]}\n'
        elif pg.get('modal_triggers'):
            output += f'  Modal Triggers: {[m["button"] for m in pg["modal_triggers"]]}\n'

        if pg.get('form_fields'):
            fields = [f'{f["identifier"]} ({f["type"]}){", required" if f.get("required") else ""}'
                      for f in pg['form_fields']]
            output += f'  Page Form Fields: {fields}\n'
        if pg.get('links'):
            output += f'  Nav Links: {[l["text"] for l in pg["links"]]}\n'
        output += '\n'

    output += '=== END PROBED LIVE APP STATE ===\n'
    return output


def _format_discovery_for_context(discovery: dict) -> str:
    """Convert project identity discovery dict into a readable context string."""
    output = '\n\n=== PROJECT IDENTITY (Discovery Agent) ===\n'
    output += f'Project Type: {discovery.get("project_type", "UNKNOWN")}\n'
    output += f'Base URL: {discovery.get("base_url", "unknown")}\n'

    if discovery.get('tech_stack'):
        output += f'Tech Stack: {json.dumps(discovery["tech_stack"], indent=2)}\n'

    if discovery.get('routes'):
        output += f'Routes ({len(discovery["routes"])}): {discovery["routes"]}\n'

    if discovery.get('env_keys'):
        output += f'Environment Keys: {discovery["env_keys"]}\n'

    if discovery.get('login_metadata'):
        lm = discovery['login_metadata']
        output += f'Auth Files: {lm.get("auth_files", [])}\n'
        output += f'Auth Fields: {lm.get("fields", [])}\n'
        output += f'Validation Library: {lm.get("validation_library", "none")}\n'

    output += '=== END PROJECT IDENTITY ===\n'
    return output


def _clone_and_read(
    provider: str,
    repo_name: str,
    temp_dir: str,
    git_token: str | None,
    git_host: str | None,
) -> str:
    """Clone the repo into *temp_dir* and return concatenated file content.

    This is a **blocking** helper – called via ``asyncio.to_thread``.
    """
    clone_url = _build_clone_url(provider, repo_name, git_token, git_host)
    _clone_repo(clone_url, temp_dir)
    return _read_repo_files(temp_dir)


async def _call_gemini_pro(code_context: str) -> str:
    """Helper to call Gemini Pro with the given code context."""
    api_key = os.getenv('GEMINI_API_KEY') or 'AIzaSyCSbFI5wZl9pQnCRvrjT511aft82DjjiFQ'
    ai_client = genai.Client(api_key=api_key)

    response = await asyncio.to_thread(
        ai_client.models.generate_content,
        model='gemini-3-pro-preview',
        contents=f"{SYSTEM_PROMPT}\n\nHere is the full codebase:\n{code_context}",
    )
    return response.text


# ---------------------------------------------------------------------------
# Background Job Logic
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Background Job Logic
# ---------------------------------------------------------------------------
async def generate_docs_logic(
    job_id: str,
    repo_name: str,
    provider: str,
    git_token: str | None,
    git_host: str | None,
) -> None:
    """Heavy async task: clone → universal scan → Gemini Pro (w/ retries) → store result.

    Updates ``jobs[job_id]`` with status, markdown, or error.
    """
    safe_name = repo_name.replace('/', '_')
    temp_dir = f'/tmp/sandbox_docs_{safe_name}_{uuid.uuid4().hex[:8]}'

    try:
        # 1. Update status
        jobs[job_id]['status'] = 'cloning'
        logger.info(f'[{job_id}] Cloning {repo_name}...')

        # Clone (blocking)
        clone_url = _build_clone_url(provider, repo_name, git_token, git_host)
        await asyncio.to_thread(_clone_repo, clone_url, temp_dir)

        # 1. WAIT & STABILIZE
        print(f"[{job_id}] Repo cloned. Stabilizing filesystem (3s)...")
        await asyncio.sleep(3)

        # ══════════════════════════════════════════════════════════════
        # PHASE 1: IDENTITY & URL DISCOVERY
        # ══════════════════════════════════════════════════════════════
        jobs[job_id]['status'] = 'discovering'
        print(f"[{job_id}] Phase 1: Identity & URL Discovery...")

        discovery = await asyncio.to_thread(_discover_project_identity, temp_dir)
        project_type = discovery.get('project_type', 'UNKNOWN')

        # Feature detection (quick scan for context headers)
        features_detected = []
        for root, dirs, files in os.walk(temp_dir):
            dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build', '.next']]
            for f in files:
                fl = f.lower()
                if 'auth' in fl or 'login' in fl:
                    features_detected.append('AUTHENTICATION')
                if 'table' in fl or 'datagrid' in fl:
                    features_detected.append('DATA_MANAGEMENT')
                if 'chart' in fl or 'stats' in fl:
                    features_detected.append('ANALYTICS')
        features_detected = list(set(features_detected))

        # Smart Filters
        ignore_dirs = ['node_modules', '.git', 'dist', 'build', 'coverage', 'assets', 'public', '.next']
        ignore_files = ['package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'tailwind.config.js', 'postcss.config.js']
        valid_exts = ('.tsx', '.ts', '.jsx', '.js', '.vue', '.py')

        # ══════════════════════════════════════════════════════════════
        # PHASE 1.5: DEEP LOGIC TRACER (Core Method Probe)
        # ══════════════════════════════════════════════════════════════
        core_logic_files = []
        core_keywords = ['slice', 'context', 'service', 'store', 'api', 'reducer', 'action', 'middleware', 'provider']
        for root, dirs, files in os.walk(temp_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for f in files:
                if any(k in f.lower() for k in core_keywords):
                    core_logic_files.append(os.path.join(root, f))

        print(f"[{job_id}] Deep Logic Tracer found {len(core_logic_files)} core logic files.")
        for clf in core_logic_files:
            print(f"  [CORE] {os.path.relpath(clf, temp_dir)}")

        # ══════════════════════════════════════════════════════════════
        # PHASE 1.6: COMPONENT AUDITOR (Static UI Action Map)
        # ══════════════════════════════════════════════════════════════
        print(f"[{job_id}] Running Component Auditor...")
        ui_action_map = _build_ui_action_map(temp_dir)

        # ══════════════════════════════════════════════════════════════
        # PHASE 2: PLAYWRIGHT SCRAPER (Live Visual Truth) – Optional
        # ══════════════════════════════════════════════════════════════
        jobs[job_id]['status'] = 'scraping'
        scraped_data = {'status': 'skipped', 'pages': []}
        login_selectors = discovery.get('login_metadata', {}).get('login_selectors', {})

        if HAS_PLAYWRIGHT and discovery.get('routes'):
            print(f"[{job_id}] Phase 2: WebsiteReader Live Crawl...")
            reader = WebsiteReader(
                repo_dir=temp_dir,
                base_url=discovery.get('base_url', 'http://localhost:3000'),
                routes=discovery['routes'],
                login_selectors=login_selectors,
            )
            try:
                scraped_data = await reader.crawl()
                # Save live_app_state.json for debugging
                reader.save_state(temp_dir)
            except Exception as scrape_err:
                print(f"[{job_id}] WebsiteReader failed (non-fatal): {scrape_err}")
                scraped_data = {'status': 'failed', 'reason': str(scrape_err)[:200], 'pages': []}
            finally:
                await reader.cleanup()
        else:
            reason = 'no playwright' if not HAS_PLAYWRIGHT else 'no routes discovered'
            print(f"[{job_id}] Skipping WebsiteReader ({reason}).")
        # ══════════════════════════════════════════════════════════════
        # PHASE 2.5: DATA FLOW TRACER (onSubmit → API mapping)
        # ══════════════════════════════════════════════════════════════
        print(f"[{job_id}] Running Data Flow Tracer...")
        data_flow_context = await asyncio.to_thread(_trace_data_flow, temp_dir)

        # ══════════════════════════════════════════════════════════════
        # PHASE 3: CONTEXT ASSEMBLY (Merge all data sources)
        # ══════════════════════════════════════════════════════════════
        jobs[job_id]['status'] = 'generating'
        print(f"[{job_id}] Phase 3: Assembling context for documentation...")

        # Build the context in priority order
        code_context = f"--- PROJECT_IDENTITY: {project_type} ---\n"
        code_context += f"--- DETECTED_FEATURES: {', '.join(features_detected)} ---\n"
        code_context += f"--- CORE_LOGIC_FILES: {len(core_logic_files)} found ---\n"

        # Inject Discovery Agent results
        code_context += _format_discovery_for_context(discovery)

        # Inject Live Scrape Data (if available)
        scrape_context = _format_scrape_for_context(scraped_data)
        if scrape_context:
            code_context += scrape_context
            print(f"[{job_id}] Probed Live App State injected ({len(scrape_context)} chars).")
        else:
            print(f"[{job_id}] No Live App State available – using static analysis only.")

        # Inject Data Flow Traces
        if data_flow_context:
            code_context += data_flow_context
            print(f"[{job_id}] Data Flow Traces injected ({len(data_flow_context)} chars).")

        # Inject UI Action Map (static fallback / supplement)
        code_context += ui_action_map

        total_chars = len(code_context)
        file_count = 0

        # Inject core logic files first with priority tag
        for clf_path in core_logic_files:
            try:
                with open(clf_path, 'r', encoding='utf-8', errors='ignore') as f:
                    clf_content = f.read()
                if len(clf_content) > 20:
                    rel_path = os.path.relpath(clf_path, temp_dir)
                    code_context += (
                        f"\n\n--- FILE: {rel_path} [CORE_LOGIC] ---\n"
                        f"{clf_content}\n"
                    )
                    total_chars += len(clf_content)
                    file_count += 1
            except Exception:
                pass

        for root, dirs, files in os.walk(temp_dir):
            # Remove junk folders from the walk
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

            for file in files:
                if file in ignore_files or file.startswith('.'):
                    continue

                if file.endswith(valid_exts):
                    # Skip tests and minified files
                    if '.test.' in file or '.spec.' in file or '.min.' in file:
                        continue

                    path = os.path.join(root, file)
                    try:
                        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()

                            # VISUAL & LOGIC FILTER
                            # Only read files that affect the User Experience (UI or Logic)
                            if len(content) > 50:
                                # Heuristic: Does this file look like it DOES something?
                                if any(k in content for k in ['function', 'class', 'return', '<div', 'onClick', 'useState', 'useEffect']):
                                    rel_path = os.path.relpath(path, temp_dir)
                                    # Skip if already added as core logic
                                    if path not in core_logic_files:
                                        code_context += f"\n\n--- FILE: {rel_path} ---\n{content}\n"
                                        total_chars += len(content)
                                        file_count += 1
                    except:
                        pass

        # 3. VERIFY DATA & FAIL SAFE
        print(f"[{job_id}] Audit Complete. Found {file_count} files ({total_chars} chars).")
        if file_count == 0:
            print(f"[{job_id}] DEBUG: Root structure:")
            for r, d, f in os.walk(temp_dir):
                print(f" {r}: {f[:3]}")
                break
            raise Exception("Analysis Failed: No source code found. Check if the repo is empty or nested.")

        # ══════════════════════════════════════════════════════════════
        # PHASE 3.5: SIDEBAR STRUCTURE (Content Architecture)
        # ══════════════════════════════════════════════════════════════
        print(f"[{job_id}] Building Sidebar Structure...")
        sidebar_structure = _build_sidebar_structure(
            discovery=discovery,
            features_detected=features_detected,
            scraped_data=scraped_data,
            repo_dir=temp_dir,
        )

        # Inject sidebar manifest into context
        sidebar_context = _format_sidebar_for_context(sidebar_structure)
        code_context += sidebar_context
        print(f"[{job_id}] Sidebar manifest injected ({len(sidebar_context)} chars).")

        # Save sidebar_structure.json
        sidebar_path = os.path.join(temp_dir, 'sidebar_structure.json')
        try:
            with open(sidebar_path, 'w', encoding='utf-8') as f:
                json.dump(sidebar_structure, f, indent=2, default=str)
            print(f"[{job_id}] sidebar_structure.json saved to {sidebar_path}")
        except Exception as e:
            print(f"[{job_id}] Failed to save sidebar_structure.json: {e}")

        # 4. AUTO-THROTTLE & GEMINI CALL (Main Module Docs)
        api_key = os.getenv('GEMINI_API_KEY') or 'AIzaSyCSbFI5wZl9pQnCRvrjT511aft82DjjiFQ'
        ai_client = genai.Client(api_key=api_key)

        max_retries = 3
        retry_time = 40
        markdown_output = ""

        for attempt in range(max_retries):
            try:
                print(f"[{job_id}] Generating Module Documentation (Attempt {attempt+1})...")
                response = await asyncio.to_thread(
                    ai_client.models.generate_content,
                    model='gemini-3-pro-preview',
                    contents=f"{SYSTEM_PROMPT}\n\nHere is the full codebase:\n{code_context}",
                )
                markdown_output = response.text
                break

            except exceptions.ResourceExhausted:
                print(f"[{job_id}] Rate Limit Hit (429). Pausing for {retry_time}s...")
                await asyncio.sleep(retry_time)
                retry_time += 20

            except Exception as e:
                print(f"[{job_id}] API Error: {str(e)}")
                raise e

        if not markdown_output:
            raise Exception("Failed to generate documentation. Server is too busy.")

        # ══════════════════════════════════════════════════════════════
        # PHASE 4: ENGINEER'S BLUEPRINT (Separate Technical Doc)
        # ══════════════════════════════════════════════════════════════
        engineer_blueprint = ""
        try:
            print(f"[{job_id}] Generating Engineer's Blueprint...")
            # Build a focused context for the blueprint (tech-heavy)
            blueprint_context = f"--- PROJECT_IDENTITY: {project_type} ---\n"
            blueprint_context += _format_discovery_for_context(discovery)
            if data_flow_context:
                blueprint_context += data_flow_context

            # Include package.json for tech stack audit
            pkg_path = os.path.join(temp_dir, 'package.json')
            if os.path.isfile(pkg_path):
                try:
                    with open(pkg_path, 'r', encoding='utf-8') as f:
                        blueprint_context += f"\n\n--- FILE: package.json ---\n{f.read()}\n"
                except Exception:
                    pass

            # Include .env files
            for env_name in ['.env', '.env.example', '.env.local']:
                env_path = os.path.join(temp_dir, env_name)
                if os.path.isfile(env_path):
                    try:
                        with open(env_path, 'r', encoding='utf-8') as f:
                            blueprint_context += f"\n\n--- FILE: {env_name} ---\n{f.read()}\n"
                    except Exception:
                        pass

            # Include core logic files (services, api, auth)
            for clf_path in core_logic_files[:10]:
                try:
                    with open(clf_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    if len(content) > 20:
                        rel = os.path.relpath(clf_path, temp_dir)
                        blueprint_context += f"\n\n--- FILE: {rel} [CORE_LOGIC] ---\n{content}\n"
                except Exception:
                    pass

            await asyncio.sleep(5)  # Brief pause between Gemini calls

            bp_response = await asyncio.to_thread(
                ai_client.models.generate_content,
                model='gemini-3-pro-preview',
                contents=f"{ENGINEER_BLUEPRINT_PROMPT}\n\nHere is the technical context:\n{blueprint_context}",
            )
            engineer_blueprint = bp_response.text
            print(f"[{job_id}] Engineer's Blueprint generated ({len(engineer_blueprint)} chars).")

        except exceptions.ResourceExhausted:
            print(f"[{job_id}] Rate limit on blueprint generation. Skipping.")
        except Exception as e:
            print(f"[{job_id}] Blueprint generation failed (non-fatal): {str(e)[:200]}")

        # ══════════════════════════════════════════════════════════════
        # PHASE 5: POST-PROCESSING (Split into per-module files)
        # ══════════════════════════════════════════════════════════════
        print(f"[{job_id}] Phase 5: Splitting output into per-module files...")
        documentation = _split_docs_by_module(markdown_output, sidebar_structure)

        # Add engineer blueprint to documentation
        if engineer_blueprint:
            documentation['engineer-blueprint.md'] = engineer_blueprint

        print(f"[{job_id}] Total documentation files: {len(documentation)}")
        for fname, content in documentation.items():
            print(f"  → {fname}: {len(content)} chars")

        # 5. Save Result
        jobs[job_id].update({
            'status': 'completed',
            'markdown': markdown_output,
            'repo_name': repo_name,
            'provider': provider,
            'sidebar_structure': sidebar_structure,
            'documentation': documentation,
            'engineer_blueprint': engineer_blueprint,
        })
        logger.info(f'[{job_id}] Success. Generated {len(markdown_output)} chars + {len(documentation)} module files.')

    except Exception as exc:
        logger.exception(f'[{job_id}] Failed: {exc}')
        jobs[job_id].update({
            'status': 'failed',
            'error': str(exc),
        })
    finally:
        # Cleanup
        if os.path.exists(temp_dir):
            print(f"[{job_id}] Cleanup: removing {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# POST Endpoint – Submit Job
# ---------------------------------------------------------------------------
@app.post("/generate-docs")
async def generate_documentation(
    request: DocRequest,
    background_tasks: BackgroundTasks,
    provider_tokens: PROVIDER_TOKEN_TYPE | None = Depends(get_provider_tokens),
) -> JSONResponse:
    print(f"\n{'='*60}")
    print(f"[POST] New doc job for {request.provider}:{request.repo_name}")
    print(f"{'='*60}\n")

    if request.provider not in ('github', 'gitlab'):
        raise HTTPException(
            status_code=400,
            detail="Invalid provider. Must be 'github' or 'gitlab'.",
        )

    # Resolve token & host from settings
    git_token: str | None = None
    git_host: str | None = None

    if provider_tokens:
        ptype = (
            ProviderType.GITHUB if request.provider == 'github' else ProviderType.GITLAB
        )
        if ptype in provider_tokens:
            ptoken_obj = provider_tokens[ptype]
            if ptoken_obj.token:
                git_token = ptoken_obj.token.get_secret_value()
            if ptoken_obj.host:
                git_host = ptoken_obj.host

    # Fallback to env vars if not in settings (optional legacy support)
    if not git_token:
        if request.provider == 'github':
            git_token = os.getenv('GITHUB_TOKEN')
        elif request.provider == 'gitlab':
            git_token = os.getenv('GITLAB_TOKEN')

    if not git_host and request.provider == 'gitlab':
        # Legacy env var support for GitLab host
        git_host = os.getenv('GITLAB_HOST')

    job_id = uuid.uuid4().hex
    jobs[job_id] = {'status': 'processing'}

    # Schedule the heavy work in the background
    background_tasks.add_task(
        generate_docs_logic,
        job_id,
        request.repo_name,
        request.provider,
        git_token,
        git_host,
    )

    logger.info(f'[POST] Job {job_id} queued for {request.provider}:{request.repo_name}')

    return JSONResponse(content={'job_id': job_id})


# ---------------------------------------------------------------------------
# GET Endpoint – Poll Job Status (zero logic, dict lookup only)
# ---------------------------------------------------------------------------
@app.get("/generate-docs/{job_id}")
async def get_job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return {"status": "not_found"}
    return job

