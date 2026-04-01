from typing import Any

from app.handlers.code_review_handler import code_review_handler
from app.mcp import MCPTool


TOOL_CODE_REVIEW = MCPTool(
    name="code_review",
    description="Perform code review on a repository. Analyzes git diff and returns findings with severity, title, message, and suggestions. Use this when user asks to review code, changes, or a pull request.",
    input_schema={
        "type": "object",
        "properties": {
            "repo_name": {
                "type": "string",
                "description": "Name of the repository to review"
            },
            "project_name": {
                "type": "string",
                "description": "Name of the project (optional if session has active project)"
            },
            "target": {
                "type": "string",
                "description": "Target branch/commit for comparison (default: HEAD)",
                "default": "HEAD"
            },
            "base": {
                "type": "string",
                "description": "Base branch for diff comparison (optional, leave empty for uncommitted changes)"
            }
        },
        "required": ["repo_name"]
    }
)


async def builtin_code_review(args: dict[str, Any]) -> str:
    """Execute code review on a repository."""
    repo_name = args.get("repo_name")
    project_name = args.get("project_name")
    target = args.get("target", "HEAD")
    base = args.get("base")
    
    if not repo_name:
        return "Error: repo_name is required"
    
    if not project_name:
        return "Error: project_name is required (or set project in session)"
    
    try:
        review_result = code_review_handler.review(
            project=project_name,
            repo=repo_name,
            target=target,
            base=base,
            include_rag=True
        )
        
        parts = [f"# Code Review: {repo_name}"]
        parts.append(f"\n**Target:** {target}")
        if base:
            parts.append(f"**Base:** {base}")
        parts.append("\n---\n")
        
        if review_result.findings:
            parts.append(f"\n## Findings ({len(review_result.findings)})\n")
            for i, finding in enumerate(review_result.findings, 1):
                parts.append(f"\n### {i}. [{finding.severity.upper()}] {finding.title}")
                parts.append(f"\n{finding.message}")
                if finding.suggestion:
                    parts.append(f"\n**Suggestion:** {finding.suggestion}")
        
        if review_result.detailed:
            parts.append(f"\n\n## Details\n{review_result.detailed[:3000]}")
        
        if not review_result.findings and not review_result.detailed:
            parts.append("\nNo issues found.")
        
        return "".join(parts)
    
    except Exception as e:
        return f"Error performing code review: {str(e)}"
