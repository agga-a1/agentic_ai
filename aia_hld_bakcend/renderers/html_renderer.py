import json

def render_hld_html(
    document_name: str,
    project_name: str,
    architecture_overview: dict,
    static_diagram: str,
    nfr: dict,
    security_controls: list,
) -> str:

    # 1. Handle Architecture Overview Narrative & Components
    narrative = architecture_overview.get("high_level_design_narrative", "No narrative provided.")
    components = architecture_overview.get("component_breakdown", [])
    
    components_html = ""
    if components:
        components_html = "<h3>Component Breakdown</h3>\n<ul>\n"
        for comp in components:
            name = comp.get("component_name", "Unknown Component")
            role = comp.get("role", "No role described.")
            components_html += f"<li><strong>{name}:</strong> {role}</li>\n"
        components_html += "</ul>"

    arch_overview_html = f"<p>{narrative}</p>\n{components_html}"

    # 2. Handle Diagram
    diagram_html = ""
    if static_diagram:
        diagram_html = f"""
        <h2>Architecture Diagram</h2>
        <pre class="mermaid">
{static_diagram}
        </pre>
        """

    # 3. Handle Non-Functional Requirements (NFR)
    nfr_html = "<ul>\n"
    if nfr:
        for key, value in nfr.items():
            # Clean up the key name (e.g., 'security_nfr' -> 'Security Nfr')
            display_key = str(key).replace("_", " ").title()
            nfr_html += f"<li><strong>{display_key}:</strong> {value}</li>\n"
    else:
        nfr_html += "<li>No non-functional requirements specified.</li>\n"
    nfr_html += "</ul>"

    # 4. Handle Security Controls
    sec_html = "<ul>\n"
    if security_controls:
        for c in security_controls:
            sec_html += f"<li>{c}</li>\n"
    else:
        sec_html += "<li>No specific security controls identified.</li>\n"
    sec_html += "</ul>"


    # 5. Build Final HTML
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>{document_name}</title>

    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{
            startOnLoad: true,
            theme: "default"
        }});
    </script>

    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            line-height: 1.6;
            color: #333;
        }}
        h1, h2, h3 {{
            color: #E60000; /* Red */
        }}
        h1 {{
            border-bottom: 2px solid #E60000;
            padding-bottom: 10px;
        }}
        p {{
            margin-bottom: 15px;
        }}
        ul {{
            margin-bottom: 20px;
        }}
        li {{
            margin-bottom: 8px;
        }}
        pre.mermaid {{
            background: #f4f4f4;
            padding: 15px;
            border-radius: 4px;
            text-align: center;
        }}
    </style>
</head>

<body>
    <h1>{document_name}</h1>
    <h3>Project: {project_name}</h3>

    <h2>Architecture Overview</h2>
    {arch_overview_html}

    {diagram_html}

    <h2>Non-Functional Requirements</h2>
    {nfr_html}

    <h2>Security Controls</h2>
    {sec_html}

</body>
</html>
"""