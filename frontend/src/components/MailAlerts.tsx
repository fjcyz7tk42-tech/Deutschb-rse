// Mail alerts for one stock: addresses entered here get a mail for each new live announcement on it
// (live/notify.py). Each address also gets a confirmation mail with an unsubscribe link.
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import axios from 'axios';
import {
  addSubscription, getSubscriptions, removeSubscription, sendTestAlert, type MailInfo, type Subscription,
} from '../liveApi';

interface Props {
  isin: string;
  ticker: string;
}

function errorText(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const detail = e.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (!e.response) return 'Live feed not reachable.';
  }
  return 'Could not save the address.';
}

export default function MailAlerts({ isin, ticker }: Props) {
  const [subs, setSubs] = useState<Subscription[] | null>(null);
  const [mail, setMail] = useState<MailInfo | null>(null);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; error: boolean } | null>(null);

  const load = useCallback(() => {
    getSubscriptions(isin)
      .then((r) => {
        setSubs(r.subscriptions);
        setMail(r.mail);
      })
      .catch(() => setSubs(null));
  }, [isin]);

  // LivePanel mounts this with key={isin}, so a stock switch starts with empty state.
  useEffect(load, [load]);

  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setMsg(null);
    addSubscription(email.trim(), isin)
      .then((r) => {
        setEmail('');
        setMail(r.mail);
        setMsg({
          text: !r.created
            ? `${r.subscription.email} already follows ${ticker}.`
            : r.mail.enabled
              ? `Added. A confirmation mail goes to ${r.subscription.email}.`
              : `Added ${r.subscription.email}.`,
          error: false,
        });
        load();
      })
      .catch((e) => setMsg({ text: errorText(e), error: true }))
      .finally(() => setBusy(false));
  };

  const test = () => {
    setBusy(true);
    setMsg(null);
    sendTestAlert(isin)
      .then((r) => {
        const where = r.mail.host === 'mailpit' ? ' View it in Mailpit: http://localhost:8025' : '';
        setMsg({ text: `Test alert sent to ${r.sent} address${r.sent === 1 ? '' : 'es'}.${where}`, error: false });
      })
      .catch((e) => setMsg({ text: errorText(e), error: true }))
      .finally(() => setBusy(false));
  };

  const remove = (s: Subscription) => {
    removeSubscription(s.id)
      .then(() => {
        setMsg({ text: `Removed ${s.email}.`, error: false });
        load();
      })
      .catch((e) => setMsg({ text: errorText(e), error: true }));
  };

  return (
    <div className="mail-alerts">
      <div className="mail-head">Mail alerts for {ticker}</div>
      <form className="mail-form" onSubmit={submit}>
        <input
          type="email"
          placeholder="name@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-label={`E-mail address for alerts on ${ticker}`}
          required
        />
        <button className="btn small" type="submit" disabled={busy}>
          {busy ? 'Adding…' : 'Add'}
        </button>
      </form>
      {msg && <div className={`mail-msg ${msg.error ? 'error' : 'muted'}`}>{msg.text}</div>}
      {subs && subs.length > 0 && (
        <ul className="mail-list">
          {subs.map((s) => (
            <li key={s.id}>
              <span>{s.email}</span>
              <button className="mail-remove" onClick={() => remove(s)} title={`Stop alerts for ${s.email}`}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {subs && subs.length > 0 && mail?.enabled && (
        <button className="btn ghost small mail-test" onClick={test} disabled={busy}>
          Send test alert
        </button>
      )}
      <div className="caption">
        {mail && !mail.enabled
          ? 'Mail delivery is off (SMTP_HOST is not set): addresses are stored, but no mail goes out.'
          : `Each address gets one mail per new announcement on ${ticker} (EQS News, tagesschau.de), holding notices excluded. Every mail has an unsubscribe link.`}
      </div>
    </div>
  );
}
