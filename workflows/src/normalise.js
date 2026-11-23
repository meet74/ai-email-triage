// Turns a Gmail Trigger item into the fields the rest of the flow uses.
// Mirrors triage/text.py; the service runs the same clean-up again, which is harmless.
const item = $input.item.json;

const stripHtml = (h) =>
  h.replace(/<(br|\/p|\/div|\/li)\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');

const addressOf = (f) => {
  if (!f) return { text: '', address: '' };
  if (typeof f === 'string') {
    const m = f.match(/<([^>]+)>/);
    return { text: f, address: m ? m[1] : f };
  }
  const v = f.value && f.value[0];
  if (v) return { text: v.name ? `${v.name} <${v.address}>` : v.address, address: v.address };
  return { text: f.text || '', address: f.text || '' };
};

const sender = addressOf(item.from);
const subject = item.subject || '';
const raw = (item.text || item.textPlain || (item.html ? stripHtml(item.html) : '') || item.snippet || '')
  .replace(/\r\n/g, '\n');

const REPLY_MARKERS = [
  /^\s*On .{5,120}wrote:\s*$/i,
  /^\s*Le .{5,120}a écrit\s*:\s*$/i,
  /^\s*El .{5,120}escribió:\s*$/i,
  /^\s*-{2,}\s*Original Message\s*-{2,}\s*$/i,
  /^\s*_{5,}\s*$/,
];
const SIGNATURE_MARKERS = [
  /^--\s?$/, /^\s*Sent from my (iPhone|iPad|Android|phone|Galaxy)/i, /^\s*Get Outlook for (iOS|Android)/i,
  /^\s*(This|The) (e-?mail|message) (and any attachments )?(is|are) confidential/i,
  /^\s*Envoyé de mon (iPhone|iPad)/i, /^\s*Enviado desde mi (iPhone|iPad|móvil)/i,
];
const FORWARD = /-{3,}\s*(Forwarded message|Message transféré|Mensaje reenviado)\s*-{3,}/i;

const lines = raw.split('\n');
let cut = -1;
for (let i = 0; i < lines.length && cut < 0; i++) {
  if (FORWARD.test(lines[i])) break; // forwarded text is content, not history
  if (lines[i].trimStart().startsWith('>') || REPLY_MARKERS.some((r) => r.test(lines[i]))) cut = i;
  else if (/^\s*From:\s.+$/i.test(lines[i]) && lines.slice(i + 1, i + 4).some((l) => /^\s*(Sent|Date|Envoyé|Enviado):/i.test(l))) cut = i;
}
let fresh = (cut < 0 ? lines : lines.slice(0, cut));
const quoted = cut < 0 ? '' : lines.slice(cut).join('\n').trim();
for (let i = 0; i < fresh.length; i++) {
  if (FORWARD.test(fresh[i])) break;
  if (SIGNATURE_MARKERS.some((r) => r.test(fresh[i]))) { fresh = fresh.slice(0, i); break; }
}
const body = fresh.join('\n').trim();

const STOP = {
  en: 'the and is are to of in for with my your you i we this that have has not was it on be can please thanks order',
  fr: 'le la les de des et est un une pour avec mon ma vous je nous ce que pas sur bonjour merci commande êtes suis',
  es: 'el la los las de y es un una para con mi su usted yo nosotros que no en hola gracias pedido por está',
  de: 'der die das und ist ein eine für mit mein ihr sie ich wir nicht auf bitte danke bestellung',
};
const words = (subject + ' ' + body).toLowerCase().match(/[a-zà-ÿ']+/g) || [];
const score = {};
for (const [lang, list] of Object.entries(STOP)) {
  const set = new Set(list.split(' '));
  score[lang] = words.slice(0, 400).filter((w) => set.has(w)).length;
}
let language = Object.keys(score).reduce((a, b) => (score[b] > score[a] ? b : a), 'en');
if (score[language] === 0 || (language !== 'en' && score[language] <= score.en)) language = 'en';

const id = String(item.id || item.messageId || Date.now());
const day = new Date().toISOString().slice(0, 10).replace(/-/g, '');

return {
  json: {
    message_id: id,
    thread_id: item.threadId || id,
    ticket_id: `T-${day}-${id.slice(-6).toUpperCase()}`,
    from: sender.text,
    from_address: sender.address,
    subject,
    body,
    thread: quoted ? [quoted] : [],
    language_hint: language,
    received_at: item.date || new Date().toISOString(),
  },
};
