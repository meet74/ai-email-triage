// Combines the normalised email and the triage result into one ticket row.
const mail = $('Normalise email').item.json;
const t = $input.item.json;
const cfg = $('Settings').first().json;
const labels = JSON.parse(cfg.gmail_labels_json || '{}');
const filtered = Boolean(t.meta && t.meta.skip_reason);

return {
  json: {
    ticket_id: mail.ticket_id,
    created_at: $now.toISO(),
    message_id: mail.message_id,
    thread_id: mail.thread_id,
    from: mail.from,
    subject: mail.subject,
    category: t.category,
    priority: t.priority,
    sentiment: t.sentiment,
    language: t.language,
    summary: t.summary,
    extracted: JSON.stringify(t.extracted),
    draft_reply: t.draft_reply,
    confidence: t.confidence,
    status: filtered ? 'filtered_' + t.meta.skip_reason : 'pending_approval',
    skip_reason: (t.meta && t.meta.skip_reason) || '',
    approved_by: '',
    updated_at: $now.toISO(),
    label_id: labels[t.category] || '',
    triage: t,
  },
};
