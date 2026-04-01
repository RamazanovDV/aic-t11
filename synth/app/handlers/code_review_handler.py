import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import config
from app.git_repo_manager import git_repo_manager
from app.llm.base import Message
from app.llm.client import LLMClient
from app.project_manager import project_manager


REVIEW_SYSTEM_PROMPT = """Ты — опытный код-ревьюер с глубокими знаниями в области безопасности, производительности и лучших практик разработки.

## Твоя задача
Провести тщательный анализ предоставленного diff и дать конструктивную обратную связь.

## Формат ответа
Ответ должен содержать:

### 1. Краткое резюме (Summary)
Общее количество найденных проблем по категориям:
- Critical (критические)
- Major (серьёзные)
- Minor (незначительные)
- Suggestions (предложения по улучшению)

### 2. Structured Findings (для каждой проблемы)
Для каждой найденной проблемы укажи:
- Файл и строка (file:line)
- Серьёзность (severity)
- Описание проблемы
- Конкретное предложение по исправлению

### 3. Подробный разбор (Detailed Analysis)
Детальное описание:
- Что именно изменилось и почему это может быть проблемой
- Потенциальные последствия
- Best practices которые нарушены
- References на документацию или стандарты

### 4. Позитивные аспекты (Positive Notes)
Что сделано хорошо в этом изменении.

## Категории для проверки
1. **Security** - уязвимости, инъекции, проблемы аутентификации
2. **Performance** - неэффективные запросы, утечки памяти
3. **Code Quality** - дублирование, сложность, читаемость
4. **Best Practices** - нарушение стандартов языка/фреймворка
5. **Testing** - отсутствие тестов для критических изменений
6. **Documentation** - отсутствие или неполнота документации

## Важно
- Будь конструктивен и вежлив
- Фокусируйся на фактах, а не предположениях
- Предлагай конкретные решения
- Если что-то непонятно — укажи это
"""


@dataclass
class ReviewFinding:
    file: str
    line: int | None
    severity: str
    category: str
    message: str
    suggestion: str | None = None


@dataclass
class CodeReview:
    review_id: str
    project: str
    repo: str
    target: str
    base: str | None
    summary: dict[str, int]
    findings: list[ReviewFinding]
    detailed: str
    created_at: str
    commit_info: dict | None = None


class CodeReviewHandler:
    def __init__(self):
        pass
    
    def _search_project_rag(self, project: str, query: str, top_k: int = 5) -> str:
        try:
            from app.embeddings.search import EmbeddingSearch
            
            indexes = []
            project_indexes = project_manager.get_embeddings_indexes(project)
            if project_indexes:
                indexes = [i for i in project_indexes if i.get("enabled", True)]
            
            if not indexes:
                return ""
            
            search_engine = EmbeddingSearch()
            all_results = []
            
            for idx in indexes:
                index_name = idx.get("name")
                try:
                    results, _ = search_engine.search(
                        query=query,
                        index_name=index_name,
                        top_k=top_k,
                    )
                    all_results.extend(results)
                except Exception:
                    continue
            
            if not all_results:
                return ""
            
            seen = {}
            for r in all_results:
                metadata = r.get("metadata", {})
                source = metadata.get("source", "")
                if source not in seen or r.get("similarity", 0) > seen[source].get("similarity", 0):
                    seen[source] = r
            
            combined = list(seen.values())
            combined.sort(key=lambda x: x.get("similarity", 0), reverse=True)
            
            if not combined:
                return ""
            
            rag_context = "\n\n## Relevant Project Documentation\n"
            for i, result in enumerate(combined[:top_k], 1):
                metadata = result.get("metadata", {})
                source = metadata.get("source", "unknown")
                content = result.get("content", "")
                similarity = result.get("similarity", 0)
                
                rag_context += f"[{i}] Source: {source} (similarity: {similarity:.2f})\n"
                rag_context += f"{content}\n\n---\n"
            
            return rag_context
            
        except Exception:
            return ""
    
    def _parse_review_response(self, response_text: str) -> tuple[dict[str, int], list[ReviewFinding], str]:
        summary = {"critical": 0, "major": 0, "minor": 0, "suggestions": 0}
        findings = []
        detailed = response_text
        
        lines = response_text.split("\n")
        current_finding = None
        in_findings = False
        finding_lines = []
        
        for line in lines:
            line = line.strip()
            
            if "## Summary" in line or "### Summary" in line:
                in_findings = False
                continue
            
            if "## Structured Findings" in line or "### Structured Findings" in line:
                in_findings = True
                continue
            
            if "## Detailed" in line or "### Detailed" in line or "## Positive" in line:
                in_findings = False
                continue
            
            if in_findings:
                if line.startswith("**") or line.startswith("- **") or line.startswith("**"):
                    if current_finding and finding_lines:
                        finding_text = "\n".join(finding_lines)
                        finding = self._parse_finding(finding_text)
                        if finding:
                            findings.append(finding)
                            severity_lower = finding.severity.lower()
                            if severity_lower in summary:
                                summary[severity_lower] += 1
                    finding_lines = [line]
                elif line.startswith("-") or line.startswith("**"):
                    finding_lines.append(line)
                elif line:
                    if finding_lines:
                        finding_lines.append(line)
        
        if current_finding and finding_lines:
            finding_text = "\n".join(finding_lines)
            finding = self._parse_finding(finding_text)
            if finding:
                findings.append(finding)
                severity_lower = finding.severity.lower()
                if severity_lower in summary:
                    summary[severity_lower] += 1
        
        return summary, findings, detailed
    
    def _parse_finding(self, text: str) -> ReviewFinding | None:
        import re
        
        file_match = re.search(r"([^\s:]+):(\d+)", text)
        file_path = file_match.group(1) if file_match else "unknown"
        line_num = int(file_match.group(2)) if file_match else None
        
        severity = "minor"
        if "critical" in text.lower() or "🔴" in text:
            severity = "critical"
        elif "major" in text.lower() or "🟠" in text or "orange" in text.lower():
            severity = "major"
        elif "suggestion" in text.lower():
            severity = "suggestions"
        
        category = "code_quality"
        if "security" in text.lower() or "инъекц" in text.lower() or "Injection" in text:
            category = "security"
        elif "performance" in text.lower() or "performance" in text.lower():
            category = "performance"
        elif "test" in text.lower():
            category = "testing"
        elif "doc" in text.lower():
            category = "documentation"
        
        parts = text.split("\n")
        message = parts[0] if parts else text[:500]
        suggestion = None
        if "suggest" in text.lower() or "рекоменд" in text.lower():
            for part in parts:
                if "suggest" in part.lower() or "рекоменд" in part.lower() or part.startswith("- "):
                    if part != message:
                        suggestion = part
                        break
        
        return ReviewFinding(
            file=file_path,
            line=line_num,
            severity=severity,
            category=category,
            message=message[:500],
            suggestion=suggestion
        )
    
    def review(
        self,
        project: str,
        repo: str,
        target: str,
        base: str | None = None,
        include_rag: bool = True
    ) -> CodeReview:
        review_id = f"rev-{uuid.uuid4().hex[:8]}"
        
        success, diff_message, diff = git_repo_manager.get_repo_diff(
            project, repo, target, base
        )
        
        if not success or not diff:
            return CodeReview(
                review_id=review_id,
                project=project,
                repo=repo,
                target=target,
                base=base,
                summary={"error": 1},
                findings=[],
                detailed=f"Failed to get diff: {diff_message}",
                created_at=datetime.utcnow().isoformat() + "Z"
            )
        
        rag_context = ""
        if include_rag:
            rag_context = self._search_project_rag(project, f"code review {target}")
        
        provider_name = config.default_provider
        model = config.get_default_model(provider_name)
        llm_client = LLMClient(provider_name, model)
        
        review_prompt = f"""## Code Diff to Review

```diff
{diff}
```

"""
        
        if rag_context:
            review_prompt += f"\n{rag_context}\n"
        
        messages = [Message(role="user", content=review_prompt, usage={})]
        
        try:
            response = llm_client.send(
                messages=messages,
                system_prompt=REVIEW_SYSTEM_PROMPT
            )
            
            response_text = response.content if hasattr(response, 'content') else str(response)
            
        except Exception as e:
            response_text = f"Error calling LLM: {str(e)}"
        
        summary, findings, detailed = self._parse_review_response(response_text)
        
        return CodeReview(
            review_id=review_id,
            project=project,
            repo=repo,
            target=target,
            base=base,
            summary=summary,
            findings=findings,
            detailed=detailed,
            created_at=datetime.utcnow().isoformat() + "Z"
        )
    
    def review_commit(
        self,
        project: str,
        repo: str,
        commit: str,
        include_rag: bool = True
    ) -> CodeReview:
        success, _, diff = git_repo_manager.get_repo_commit_diff(project, repo, commit)
        
        if not success or not diff:
            return CodeReview(
                review_id=f"rev-{uuid.uuid4().hex[:8]}",
                project=project,
                repo=repo,
                target=commit,
                base=None,
                summary={"error": 1},
                findings=[],
                detailed=f"Failed to get commit diff: {diff}",
                created_at=datetime.utcnow().isoformat() + "Z"
            )
        
        rag_context = ""
        if include_rag:
            rag_context = self._search_project_rag(project, f"code review commit {commit}")
        
        provider_name = config.default_provider
        model = config.get_default_model(provider_name)
        llm_client = LLMClient(provider_name, model)
        
        review_prompt = f"""## Commit Diff to Review

```diff
{diff}
```

Commit: {commit}

"""
        
        if rag_context:
            review_prompt += f"\n{rag_context}\n"
        
        messages = [Message(role="user", content=review_prompt, usage={})]
        
        try:
            response = llm_client.send(
                messages=messages,
                system_prompt=REVIEW_SYSTEM_PROMPT
            )
            
            response_text = response.content if hasattr(response, 'content') else str(response)
            
        except Exception as e:
            response_text = f"Error calling LLM: {str(e)}"
        
        summary, findings, detailed = self._parse_review_response(response_text)
        
        return CodeReview(
            review_id=f"rev-{uuid.uuid4().hex[:8]}",
            project=project,
            repo=repo,
            target=commit,
            base=None,
            summary=summary,
            findings=findings,
            detailed=detailed,
            created_at=datetime.utcnow().isoformat() + "Z"
        )
    
    def get_structured_output(self, review: CodeReview) -> dict:
        return {
            "review_id": review.review_id,
            "project": review.project,
            "repo": review.repo,
            "target": review.target,
            "base": review.base,
            "summary": review.summary,
            "findings": [
                {
                    "file": f.file,
                    "line": f.line,
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "suggestion": f.suggestion
                }
                for f in review.findings
            ],
            "created_at": review.created_at
        }


code_review_handler = CodeReviewHandler()
