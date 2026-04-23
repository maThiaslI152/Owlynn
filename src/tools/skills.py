"""
Skills System — Reusable prompt templates loaded from skills/ folder.
Mirrors Cowork's Skills: domain-specific knowledge that triggers on keyword match.

Each skill is a markdown file in PROJECT_ROOT/skills/ with front-matter:
---
name: Morning Briefing
triggers: [briefing, morning, daily summary]
description: Creates a daily briefing from calendar/email/tasks
---
<prompt body>
"""

import json
import logging
import re
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool
from src.config.settings import PROJECT_ROOT

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

SKILLS_DIR = PROJECT_ROOT / "skills"

ALLOWED_CATEGORIES = {"research", "writing", "productivity", "data", "communication", "general"}


@dataclass
class SkillParam:
    """A single named parameter declared by a skill."""
    name: str
    description: str
    required: bool = True
    default: Optional[str] = None


@dataclass
class SkillDefinition:
    """Structured representation of a parsed skill template."""
    file: str
    name: str
    triggers: list[str]
    description: str
    prompt: str
    category: str = "general"
    params: list[SkillParam] = field(default_factory=list)
    chain_compatible: bool = True
    version: str = "1.0"
    tools_used: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("SkillDefinition name must be non-empty")
        if not self.triggers:
            raise ValueError("SkillDefinition triggers must contain at least one entry")
        if not self.prompt or not self.prompt.strip():
            raise ValueError("SkillDefinition prompt must be non-empty")
        if self.category not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"Invalid category '{self.category}'. Must be one of: {', '.join(sorted(ALLOWED_CATEGORIES))}"
            )
        param_names = [p.name for p in self.params]
        if len(param_names) != len(set(param_names)):
            raise ValueError("SkillDefinition param names must be unique")


def _parse_front_matter(text: str) -> tuple[dict, str]:
    """Parse YAML-like front matter from a markdown skill file.

    Handles both v1.0 simple fields and v2.0 structured fields including
    multi-line ``params`` blocks with sub-fields (name, description, required,
    default) and boolean values for ``chain_compatible``.
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    meta_block, body = m.group(1), m.group(2)
    meta: dict = {}
    lines = meta_block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            i += 1
            continue
        key, val = stripped.split(":", 1)
        key = key.strip()
        val = val.strip()

        # Multi-line list block (e.g. params with structured entries)
        if val == "" and key == "params":
            param_list: list[dict] = []
            i += 1
            current_param: dict | None = None
            while i < len(lines):
                pline = lines[i]
                # Stop if we hit a top-level key (non-indented, has colon)
                if pline and not pline[0].isspace() and ":" in pline:
                    break
                pline_stripped = pline.strip()
                if not pline_stripped:
                    i += 1
                    continue
                if pline_stripped.startswith("- "):
                    # New list item — could be "- name: value" or just "- value"
                    item_content = pline_stripped[2:].strip()
                    if ":" in item_content:
                        current_param = {}
                        sub_key, sub_val = item_content.split(":", 1)
                        sub_key = sub_key.strip()
                        sub_val = sub_val.strip()
                        current_param[sub_key] = sub_val
                    else:
                        # Simple list item inside params (unlikely but handle)
                        current_param = {"name": item_content}
                    param_list.append(current_param)
                elif current_param is not None and ":" in pline_stripped:
                    # Continuation sub-field of current param
                    sub_key, sub_val = pline_stripped.split(":", 1)
                    sub_key = sub_key.strip()
                    sub_val = sub_val.strip()
                    current_param[sub_key] = sub_val
                i += 1
            meta[key] = param_list
            continue  # don't increment i again

        # Inline list syntax [item1, item2]
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        # Boolean coercion for chain_compatible
        elif key == "chain_compatible":
            val = val.strip("'\"").lower() not in ("false", "no", "0")
        else:
            # Strip surrounding quotes from plain string values
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
        meta[key] = val
        i += 1
    return meta, body.strip()


def _parse_skill_file(text: str, filename: str) -> SkillDefinition:
    """Parse a skill markdown file and return a fully-populated SkillDefinition.

    Applies v2.0 defaults for any missing fields so that v1.0 skill files
    remain backward-compatible.
    """
    meta, body = _parse_front_matter(text)

    # Build SkillParam list from parsed params dicts
    raw_params = meta.get("params", [])
    params: list[SkillParam] = []
    if isinstance(raw_params, list):
        for entry in raw_params:
            if isinstance(entry, dict):
                req_raw = entry.get("required", "true")
                if isinstance(req_raw, str):
                    required = req_raw.lower() not in ("false", "no", "0")
                else:
                    required = bool(req_raw)
                params.append(SkillParam(
                    name=entry.get("name", ""),
                    description=entry.get("description", ""),
                    required=required,
                    default=entry.get("default"),
                ))

    # Normalise tools_used to a list
    tools_used = meta.get("tools_used", [])
    if isinstance(tools_used, str):
        tools_used = [t.strip() for t in tools_used.split(",") if t.strip()]

    # Normalise triggers to a list
    triggers = meta.get("triggers", [])
    if isinstance(triggers, str):
        triggers = [triggers]

    # chain_compatible — already parsed as bool by _parse_front_matter when
    # present; default to True when absent.
    chain_compatible = meta.get("chain_compatible", True)
    if isinstance(chain_compatible, str):
        chain_compatible = chain_compatible.lower() not in ("false", "no", "0")

    return SkillDefinition(
        file=filename,
        name=meta.get("name", Path(filename).stem),
        triggers=triggers,
        description=meta.get("description", ""),
        prompt=body,
        category=meta.get("category", "general"),
        params=params,
        chain_compatible=chain_compatible,
        version=meta.get("version", "1.0"),
        tools_used=tools_used,
    )


logger = logging.getLogger(__name__)


class SkillLoader:
    """Loads, parses, and caches skill definitions from ``skills/*.md``."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir
        self._cache: dict[str, SkillDefinition] = {}
        self._last_scan: float = 0.0
        self._cache_ttl: float = 30.0

    def load_all(self) -> list[SkillDefinition]:
        """Parse all ``.md`` files in skills_dir; return cached list if within TTL."""
        if self._cache and time.time() - self._last_scan < self._cache_ttl:
            return list(self._cache.values())

        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._cache.clear()
        for f in sorted(self._skills_dir.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
                skill = _parse_skill_file(text, f.name)
                self._cache[f.name] = skill
            except Exception as exc:
                logger.warning("Skipping skill file %s: %s", f.name, exc)
                continue
        self._last_scan = time.time()
        return list(self._cache.values())

    def load_one(self, filename: str) -> Optional[SkillDefinition]:
        """Parse a single skill file and return its definition, or ``None``."""
        path = self._skills_dir / filename
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            skill = _parse_skill_file(text, filename)
            self._cache[filename] = skill
            return skill
        except Exception as exc:
            logger.warning("Skipping skill file %s: %s", filename, exc)
            return None

    def invalidate_cache(self) -> None:
        """Clear the cache so the next ``load_all`` re-reads from disk."""
        self._cache.clear()
        self._last_scan = 0.0

    def get_by_name(self, name: str) -> Optional[SkillDefinition]:
        """Lookup a cached skill by name (case-insensitive)."""
        if not self._cache:
            self.load_all()
        name_lower = name.lower()
        for skill in self._cache.values():
            if skill.name.lower() == name_lower:
                return skill
        return None

    def get_by_category(self, category: str) -> list[SkillDefinition]:
        """Return all cached skills belonging to *category*."""
        if not self._cache:
            self.load_all()
        return [s for s in self._cache.values() if s.category == category]


_default_loader = SkillLoader(SKILLS_DIR)


class SkillMatcher:
    """Hybrid matching engine combining keyword triggers with TF-IDF similarity scoring."""

    def __init__(self, loader: SkillLoader) -> None:
        self._loader = loader
        self._tfidf_matrix = None
        self._vectorizer = None
        self._skill_names: list[str] = []

    def match(self, query: str, top_k: int = 3) -> list[tuple[SkillDefinition, float]]:
        """Return up to *top_k* skills whose combined score meets the threshold.

        Combined score = 0.6 * keyword + 0.4 * semantic.
        Results are sorted by score descending.
        """
        KEYWORD_WEIGHT = 0.6
        SEMANTIC_WEIGHT = 0.4
        THRESHOLD = 0.3

        skills = self._loader.load_all()
        if not skills:
            return []

        # Build a name→skill lookup for semantic results
        skill_by_name: dict[str, SkillDefinition] = {s.file: s for s in skills}

        # Keyword scores
        kw_scores: dict[str, float] = {}
        for skill in skills:
            kw_scores[skill.file] = self._keyword_score(query, skill)

        # Semantic scores (TF-IDF or empty if sklearn unavailable)
        sem_scores: dict[str, float] = {}
        if _HAS_SKLEARN:
            for name, score in self._semantic_score(query):
                sem_scores[name] = score

        # Combine
        combined: list[tuple[SkillDefinition, float]] = []
        for skill in skills:
            kw = kw_scores.get(skill.file, 0.0)
            sem = sem_scores.get(skill.file, 0.0)
            final = KEYWORD_WEIGHT * kw + SEMANTIC_WEIGHT * sem
            # Clamp to [0.0, 1.0]
            final = max(0.0, min(1.0, final))
            if final >= THRESHOLD:
                combined.append((skill, final))

        combined.sort(key=lambda x: x[1], reverse=True)
        return combined[:top_k]

    def match_best(self, query: str, threshold: float = 0.3) -> Optional[SkillDefinition]:
        """Return the single best match above *threshold*, or ``None``."""
        results = self.match(query, top_k=1)
        if results and results[0][1] >= threshold:
            return results[0][0]
        return None

    def _keyword_score(self, query: str, skill: SkillDefinition) -> float:
        """Score a skill against *query* using trigger substring / token overlap.

        - If any trigger is an exact substring of the query → 1.0
        - Otherwise, compute token overlap ratio scaled by 0.5
        - No overlap → 0.0
        """
        query_lower = query.lower()
        query_tokens = set(query_lower.split())

        # Exact substring check
        for trigger in skill.triggers:
            if trigger.lower() in query_lower:
                return 1.0

        # Partial token overlap
        trigger_tokens: set[str] = set()
        for trigger in skill.triggers:
            trigger_tokens.update(trigger.lower().split())

        overlap = query_tokens & trigger_tokens
        if overlap:
            return 0.5 * len(overlap) / max(len(trigger_tokens), 1)

        return 0.0

    def _semantic_score(self, query: str) -> list[tuple[str, float]]:
        """Compute TF-IDF cosine similarity of *query* against all loaded skills.

        Returns a list of ``(skill_file_name, similarity)`` pairs.
        Falls back to an empty list when scikit-learn is unavailable.
        """
        if not _HAS_SKLEARN:
            return []

        self._rebuild_index()

        if self._tfidf_matrix is None or self._vectorizer is None:
            return []

        query_vec = self._vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self._tfidf_matrix).flatten()

        results: list[tuple[str, float]] = []
        for i, name in enumerate(self._skill_names):
            results.append((name, float(similarities[i])))
        return results

    def _rebuild_index(self) -> None:
        """Rebuild the TF-IDF matrix from currently loaded skills."""
        if not _HAS_SKLEARN:
            return

        skills = self._loader.load_all()
        if not skills:
            self._tfidf_matrix = None
            self._vectorizer = None
            self._skill_names = []
            return

        self._skill_names = [s.file for s in skills]
        corpus = [
            f"{s.name} {s.description} {' '.join(s.triggers)}" for s in skills
        ]

        self._vectorizer = TfidfVectorizer()
        self._tfidf_matrix = self._vectorizer.fit_transform(corpus)


class ContextInjector:
    """Renders skill prompts with context, parameters, and chain state."""

    def inject(
        self,
        skill: SkillDefinition,
        context: str,
        params: Optional[dict[str, str]] = None,
        chain_state: Optional[dict] = None,
    ) -> str:
        """Render a skill prompt with context, parameters, and chain state.

        1. Validate and fill params (required check + defaults).
        2. Replace ``{context}`` and ``{input}`` placeholders.
        3. Replace ``{param_name}`` placeholders.
        4. Prepend chain header if *chain_state* has previous steps.
        """
        params = self._validate_params(skill, params or {})

        prompt = skill.prompt

        # Replace standard placeholders
        prompt = prompt.replace("{context}", context)
        prompt = prompt.replace("{input}", context)

        # Replace named param placeholders
        for key, value in params.items():
            prompt = prompt.replace(f"{{{key}}}", value)

        # Inject chain context
        if chain_state and chain_state.get("previous_steps"):
            prompt = self._apply_chain_context(prompt, chain_state)

        return prompt

    def _validate_params(self, skill: SkillDefinition, params: dict) -> dict:
        """Validate required params are present and apply defaults for optional ones.

        Raises :class:`ValueError` for any missing required parameter.
        Returns the completed params dict.
        """
        completed = dict(params)
        for sp in skill.params:
            if sp.required and sp.name not in completed:
                raise ValueError(
                    f"Missing required parameter '{sp.name}': {sp.description}"
                )
            if sp.name not in completed and sp.default is not None:
                completed[sp.name] = sp.default
        return completed

    def _apply_chain_context(self, prompt: str, chain_state: dict) -> str:
        """Prepend a chain header with step number, total, and previous step names."""
        step_num = chain_state.get("current_step", 1)
        total = chain_state.get("step_count", 1)
        prev_names = ", ".join(chain_state.get("previous_steps", []))
        chain_header = (
            f"[Chain Step {step_num}/{total} — Previous: {prev_names}]\n"
            f"Use the output from the previous step(s) as input for this step.\n\n"
        )
        return chain_header + prompt


_default_injector = ContextInjector()


@dataclass
class ChainStep:
    """A single step in a skill chain."""
    skill_name: str
    params: dict[str, str] = field(default_factory=dict)
    context_override: Optional[str] = None


@dataclass
class ChainResult:
    """Result of building a skill chain pipeline."""
    steps: list[str]  # rendered prompts per step
    instructions: str  # overall chain instructions for the LLM


class ChainPipeline:
    """Orchestrates multi-skill workflows by composing skill prompts sequentially."""

    MAX_CHAIN_LENGTH = 5

    def __init__(self, loader: SkillLoader, injector: ContextInjector) -> None:
        self._loader = loader
        self._injector = injector

    def build(self, steps: list[str | ChainStep], context: str) -> ChainResult:
        """Build a multi-skill chain by composing prompts sequentially.

        Args:
            steps: Skill names (str) or :class:`ChainStep` objects.
            context: Base context string passed to each step.

        Returns:
            A :class:`ChainResult` with rendered prompts and LLM instructions.

        Raises:
            ValueError: If the chain exceeds 5 steps, any skill is not found,
                or any skill is not chain-compatible.
        """
        if len(steps) > self.MAX_CHAIN_LENGTH:
            raise ValueError(
                f"Chain too long: {len(steps)} > {self.MAX_CHAIN_LENGTH}"
            )

        # Normalize string steps to ChainStep objects
        normalized: list[ChainStep] = []
        for step in steps:
            if isinstance(step, str):
                normalized.append(ChainStep(skill_name=step))
            else:
                normalized.append(step)

        # Validate all skills exist and are chain-compatible (before rendering)
        errors: list[str] = []
        resolved: list[SkillDefinition] = []
        for cs in normalized:
            skill = self._loader.get_by_name(cs.skill_name)
            if skill is None:
                errors.append(f"Skill not found: {cs.skill_name}")
            elif not skill.chain_compatible:
                errors.append(f"Skill not chain-compatible: {cs.skill_name}")
            else:
                resolved.append(skill)

        if errors:
            raise ValueError("; ".join(errors))

        # Build rendered prompts
        rendered_steps: list[str] = []
        chain_state: dict = {
            "step_count": len(normalized),
            "previous_steps": [],
        }

        for i, (cs, skill) in enumerate(zip(normalized, resolved)):
            chain_state["current_step"] = i + 1
            step_context = cs.context_override or context

            rendered = self._injector.inject(
                skill=skill,
                context=step_context,
                params=cs.params,
                chain_state=chain_state if i > 0 else None,
            )
            rendered_steps.append(rendered)
            chain_state["previous_steps"].append(skill.name)

        # Generate chain instructions
        step_names = [s.name for s in resolved]
        instructions = (
            f"[Skill Chain: {len(step_names)} steps]\n"
            f"Execute these skills in order, passing output from each step as context to the next:\n"
        )
        for i, name in enumerate(step_names, 1):
            instructions += f"  Step {i}: {name}\n"
        instructions += "\nComplete each step fully before moving to the next."

        return ChainResult(steps=rendered_steps, instructions=instructions)

    def validate_chain(self, steps: list[str]) -> list[str]:
        """Validate a chain of skill names without rendering.

        Returns:
            A list of error strings. Empty if the chain is valid.
        """
        errors: list[str] = []
        if len(steps) > self.MAX_CHAIN_LENGTH:
            errors.append(
                f"Chain too long: {len(steps)} > {self.MAX_CHAIN_LENGTH}"
            )
        for name in steps:
            skill = self._loader.get_by_name(name)
            if skill is None:
                errors.append(f"Skill not found: {name}")
            elif not skill.chain_compatible:
                errors.append(f"Skill not chain-compatible: {name}")
        return errors


def load_all_skills() -> list[dict]:
    """Load all skill definitions from the skills directory.

    .. deprecated::
        Use ``_default_loader.load_all()`` instead.  This wrapper converts
        :class:`SkillDefinition` objects back to plain dicts for backward
        compatibility.
    """
    warnings.warn(
        "load_all_skills() is deprecated, use SkillLoader.load_all() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    skills = _default_loader.load_all()
    return [
        {
            "file": s.file,
            "name": s.name,
            "triggers": s.triggers,
            "description": s.description,
            "prompt": s.prompt,
        }
        for s in skills
    ]


def find_matching_skill(user_text: str) -> Optional[dict]:
    """Find a skill whose triggers match the user's message.

    .. deprecated::
        Use ``_default_loader.get_by_name()`` or a :class:`SkillMatcher`
        instead.  This wrapper delegates to the default loader and checks
        triggers for backward compatibility.
    """
    warnings.warn(
        "find_matching_skill() is deprecated, use SkillLoader or SkillMatcher instead",
        DeprecationWarning,
        stacklevel=2,
    )
    lower = user_text.lower()
    for skill in _default_loader.load_all():
        triggers = skill.triggers if isinstance(skill.triggers, list) else [skill.triggers]
        for t in triggers:
            if t.lower() in lower:
                return {
                    "file": skill.file,
                    "name": skill.name,
                    "triggers": skill.triggers,
                    "description": skill.description,
                    "prompt": skill.prompt,
                }
    return None


@tool
def list_skills(category: str = "") -> str:
    """Lists available skills, optionally filtered by category.

    Args:
        category: Optional category filter (research, writing, productivity, data, communication, general). Leave empty for all.
    """
    if category:
        skills = _default_loader.get_by_category(category)
        if not skills:
            return f"No skills found in category '{category}'."
        lines = [f"📂 {category}:"]
        for s in skills:
            lines.append(f"  • {s.name}: {s.description}")
        return "\n".join(lines)

    # No category filter — return all skills grouped by category
    skills = _default_loader.load_all()
    if not skills:
        return "No skills found."

    # Group by category
    grouped: dict[str, list[SkillDefinition]] = {}
    for s in skills:
        grouped.setdefault(s.category, []).append(s)

    lines = ["📚 Available Skills:"]
    for cat in sorted(grouped):
        lines.append(f"\n📂 {cat}:")
        for s in grouped[cat]:
            lines.append(f"  • {s.name}: {s.description}")
    return "\n".join(lines)


@tool
def invoke_skill(skill_name: str, context: str = "", params: str = "") -> str:
    """Invokes a named skill with context and optional parameters.

    Args:
        skill_name: Name of the skill to invoke.
        context: Additional context to inject into the skill prompt.
        params: Optional JSON string of key-value parameters (e.g. '{"depth": "deep"}').
    """
    skill = _default_loader.get_by_name(skill_name)
    if not skill:
        all_skills = _default_loader.load_all()
        available = ", ".join(s.name for s in all_skills) or "none"
        return f"Skill '{skill_name}' not found. Available: {available}"

    params_dict: dict[str, str] = {}
    if params:
        try:
            params_dict = json.loads(params)
        except (json.JSONDecodeError, TypeError) as exc:
            return f"Invalid params JSON: {exc}"

    try:
        rendered = _default_injector.inject(skill, context, params_dict)
    except ValueError as exc:
        return f"Parameter error: {exc}"

    return f"[Skill: {skill.name}]\n\n{rendered}"


@tool
def run_skill_chain(steps: str, context: str = "") -> str:
    """Runs a sequence of skills as a chain. Steps is a comma-separated list of skill names.

    Args:
        steps: Comma-separated list of skill names to execute in order.
        context: Context string passed to each step.
    """
    if not steps or not steps.strip():
        return "Please provide at least one skill name."

    step_names = [s.strip() for s in steps.split(",") if s.strip()]
    if not step_names:
        return "Please provide at least one skill name."

    try:
        pipeline = ChainPipeline(_default_loader, _default_injector)
        result = pipeline.build(step_names, context)
    except ValueError as exc:
        return f"Chain error: {exc}"

    step_prompts = "\n\n---\n\n".join(result.steps)
    return f"{result.instructions}\n\n---\n\n{step_prompts}"
