"""Code-owned IDs accepted by the application composition layer."""

MODEL_LOOP = "tutoring.model_loop"
REVIEW = "tutoring.review_candidate"
LEGACY_REVIEW = "tutoring-vet"
LEGACY_LOOP = "tutoring-retry"


WORKFLOW_BINDINGS = {'eval-grading': {'conditions': set(), 'handlers': set()}, 'companion': {'conditions': {'direct', 'cross_scene'}, 'handlers': {'decide'}},
 'planning': {'conditions': {'finish', 'review'},
              'handlers': {'planning.checkpointer_connect',
                           'planning.checkpointer_setup',
                           'planning.context_build',
                           'planning.graph_compile',
                           'planning.graph_invoke',
                           'prepare_review',
                           'route_after_prepare',
                           'wait_for_confirmation'}},
 'reflection': {'conditions': set(), 'handlers': {'reflection.turn'}},
 'review-aspects': {'conditions': set(), 'handlers': set()},
 'sprint-intake': {'conditions': set(), 'handlers': set()},
 'task-intake': {'conditions': set(), 'handlers': set()},
 'tutoring': {'conditions': {'accepted_work',
                             'candidate',
                             'checked',
                             'fallback_or_readonly',
                             'image_reference',
                             'ready',
                             'resolved',
                             'retry'},
              'handlers': {'tutoring.apply_problem',
                           'tutoring.exit_gate',
                           'tutoring.model_loop',
                           'tutoring.result',
                           'tutoring.turn'}},
 MODEL_LOOP: {'conditions': {'candidate_without_retry',
                                   'missing_attempt_done',
                                   'needs_missing_visual',
                                   'needs_visual_redraw',
                                   'no_backup_needed',
                                   'no_candidate',
                                   'no_missing_visual',
                                   'no_visual_redraw',
                                   'retry_leak',
                                   'retry_missing_with_backup',
                                   'same_leak_with_backup'},
                    'handlers': {'backup',
                                 'finish',
                                 'missing_backup',
                                 'missing_decision',
                                 'missing_primary',
                                 'primary',
                                 'repair',
                                 'visual_decision',
                                 'visual_redraw'}},
 REVIEW: {'conditions': {'always',
                                 'authority_allowed_needs_leak_check',
                                 'authority_allowed_no_leak_check',
                                 'authority_denied',
                                 'requires_text_leak',
                                 'requires_visual_leak',
                                 'text_allowed_no_visual',
                                 'text_allowed_with_visual',
                                 'text_denied'},
                  'handlers': {'tutoring.complete_vetting'}}}


def workflow_bindings(legacy: bool, legacy_review: bool):
    if not legacy and not legacy_review:
        return WORKFLOW_BINDINGS
    aliases = {}
    if legacy:
        aliases[MODEL_LOOP] = LEGACY_LOOP
    if legacy_review:
        aliases[REVIEW] = LEGACY_REVIEW
    return {
        aliases.get(key, key): binding
        for key, binding in WORKFLOW_BINDINGS.items()
    }
