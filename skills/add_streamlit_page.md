# Add a Streamlit Page

Add a new page to the dashboard that calls backend services only. Keep all logic
in `dip/`; the page is a thin control plane.

## Preconditions
- A backend service or workflow on the `Container` already exposes the data or
  action the page needs (no business logic in the UI).

## Commonly affected files
- `ui/views/<name>_view.py` — the new page (a `render()` function)
- `ui/streamlit_app.py` — import the view and add it to the sidebar radio + the
  `main()` dispatch

## Required steps
1. Create `ui/views/<name>_view.py` with a `render()` function that reads state
   via `ui.state.get_container()` / `get_active_project_id()`.
2. Call only `container.<service>` methods; never parse, write files, or run
   commands directly in the page.
3. Import the view in `ui/streamlit_app.py` and add its label to the sidebar
   `radio` list and the `main()` dispatch.

## Constraints
- No `dip` module may import Streamlit; the dependency only points UI -> backend.

## Verification commands
- `python -m pytest`
- Headless render check with `streamlit.testing.v1.AppTest`

## Common mistakes
- Putting service wiring in the page instead of the `Container`.
- Forgetting to add the page to both the radio list and the `main()` dispatch.
