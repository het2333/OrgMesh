export type RunState = 'queued' | 'running' | 'completed' | 'cancelled' | 'failed'
export type ProposalState = 'ready' | 'accepted' | 'rejected' | 'stale' | 'expired'
export interface SelectionRef {
  version_id: string
  content_hash: string
  schema_version: string
  from: number
  to: number
  selected_text_hash: string
}
export interface DocumentSnapshot {
  document_id: string
  version_id: string
  content_hash: string
  title: string
  project_id: string | null
}
export interface VersionResult extends DocumentSnapshot {
  parent_version_id: string | null
  operation: 'import' | 'manual' | 'ai_accept' | 'restore'
}
export interface CandidateInput {
  run_id: string
  selection_ref: SelectionRef
  replacement_text: string
}
export interface CandidateResult {
  candidate_hash: string
  diff: Array<{ kind: 'equal' | 'insert' | 'delete'; text: string }>
  unchanged_parts_ok: boolean
}
export interface RunRef {
  run_id: string
  chat_session_id: string
}
export interface RunEvent {
  schema_version: 1
  run_id: string
  sequence: number
  event_id: string
  type:
    | 'message_delta'
    | 'tool_started'
    | 'tool_finished'
    | 'proposal_ready'
    | 'run_completed'
    | 'run_cancelled'
    | 'run_failed'
  payload: Record<string, unknown>
}
