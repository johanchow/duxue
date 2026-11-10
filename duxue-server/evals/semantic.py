"""Independent scoring through an Admin-owned, pinned model component."""

from app.infrastructure.ai import components
from app.agent_specs.contexts import build_context


class SemanticGrader:
    def __init__(self, *, settings_obj=None, spec=None):
        self.spec = spec or components.COMPONENTS.get("evals.semantic-judge")
        self.settings = settings_obj

    def metadata(self):
        s = self.spec
        return {
            "judge_model": s.model,
            "judge_component": s.component_id,
            "judge_version": s.version,
            "judge_prompt_digest": s.prompt.digest,
            "judge_definition_digest": s.definition_digest,
            "judge_parameters": {
                "temperature": s.temperature,
                "max_output_tokens": s.max_tokens,
                "timeout_seconds": s.timeout_seconds,
            },
        }

    def grade(self, rule, *, evidence, image_pairs, reference=None, criteria=None):
        if image_pairs and not self.spec.accepts_images:
            raise ValueError("semantic grader cannot receive required images")
        payload = {
            "rubric": rule.instructions(),
            "type": rule.type,
            "case_criteria": criteria or [],
            "delivery_contract": {
                "version": "tutoring-visible-response.v1",
                "visible_fields": ["message", "visual", "lessons"],
                "description": "message是正文，visual是展示配图，lessons是实际展示的读音卡，三者共同构成回复；不是隐藏模型字段。正文不必重复读音卡的发音指导。未提供音频，不判断音频质量。",
            },
            "output_contract": {
                "required": [
                    "score" if rule.type == "score" else "verdict",
                    "explanation",
                    "evidence",
                ],
                "result": {"score": "1到5整数"}
                if rule.type == "score"
                else {"verdict": ["pass", "fail"]},
                "explanation": "简述具体理由，不超过200字",
                "evidence": "1到3个简短证据引用，不复述整段对话",
                "additional_fields": False,
            },
            "evidence": evidence,
            "reference_response": reference,
            "image_manifest": [
                {"index": i + 1, "asset": name}
                for i, (name, _) in enumerate(image_pairs)
            ],
        }
        user = build_context(
            self.spec.component_id,
            payload=payload,
            images=[url for _, url in image_pairs],
        )
        output = components.invoke_json_component(
            spec=self.spec, user=user, settings_obj=self.settings
        )
        if output.get("error"):
            raise ValueError(output["error"])
        return output
