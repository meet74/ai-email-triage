// Reduces a Slack interaction payload to what the handler needs.
// kind: approve | reject | edit | submit_edit | ignore
const p = $input.item.json.payload;
const out = {
  kind: 'ignore',
  ticket_id: '',
  user: (p.user && (p.user.username || p.user.name || p.user.id)) || 'unknown',
  trigger_id: p.trigger_id || '',
  response_url: p.response_url || '',
  edited_text: '',
};

if (p.type === 'block_actions' && p.actions && p.actions[0]) {
  const a = p.actions[0];
  out.ticket_id = a.value || '';
  out.kind = { approve_reply: 'approve', reject_reply: 'reject', edit_reply: 'edit' }[a.action_id] || 'ignore';
} else if (p.type === 'view_submission' && p.view && p.view.callback_id === 'edit_reply_submit') {
  out.kind = 'submit_edit';
  out.ticket_id = p.view.private_metadata || '';
  const v = p.view.state && p.view.state.values && p.view.state.values.draft_block;
  out.edited_text = (v && v.draft_input && v.draft_input.value) || '';
  if (!out.edited_text.trim()) out.kind = 'ignore'; // never send an empty reply
}
if (!/^T-[A-Za-z0-9-]+$/.test(out.ticket_id)) out.kind = 'ignore';
return { json: out };
