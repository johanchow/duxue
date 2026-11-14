import type { debugCapability } from '../lib/debug-capability';

type Props = {
  capability: ReturnType<typeof debugCapability>;
  catalogSource: string;
  sourceDraftId?: string;
  hasRelease: boolean;
  editingDraftId: string | null;
  draftLoaded: boolean;
  busy: boolean;
  onPublishedDebug: () => void;
  onDraftDebug: (id: string) => void;
  navigate: (url: string) => void;
};

export function AgentDebugActions(props: Props) {
  const { capability, editingDraftId } = props;
  if (!capability.supported) {
    return (
      <>
        <span className="badge" title={capability.reason}>
          未开放独立调试
        </span>
        {capability.workflowId && (
          <button
            className="secondary"
            onClick={() =>
              props.navigate(`/workflows/${capability.workflowId}`)
            }
          >
            打开所属 Workflow
          </button>
        )}
      </>
    );
  }
  const draftId =
    editingDraftId ||
    (props.catalogSource === 'admin-draft' ? props.sourceDraftId : undefined);
  if (draftId) {
    if (editingDraftId && !props.draftLoaded) return null;
    return (
      <button
        className="secondary"
        disabled={props.busy}
        onClick={() => props.onDraftDebug(draftId)}
      >
        调试已保存草稿
      </button>
    );
  }
  if (props.hasRelease && props.catalogSource === 'admin-release') {
    return (
      <button
        className="secondary"
        disabled={props.busy}
        onClick={props.onPublishedDebug}
      >
        调试已发布配置
      </button>
    );
  }
  return null;
}
