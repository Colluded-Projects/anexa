import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// --- buttons ---------------------------------------------------------------

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-hover border-transparent",
  secondary: "bg-surface text-ink border-line-strong hover:bg-sunken",
  ghost: "bg-transparent text-muted border-transparent hover:bg-sunken hover:text-ink",
  danger: "bg-surface text-danger border-line-strong hover:bg-danger-soft",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  busy?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  busy = false,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md border font-medium whitespace-nowrap",
        "transition-colors disabled:cursor-not-allowed disabled:opacity-55",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {busy && <Spinner small />}
      {children}
    </button>
  );
}

// --- form controls ---------------------------------------------------------

const CONTROL =
  "block w-full rounded-md border border-line-strong bg-surface px-3 text-sm text-ink " +
  "disabled:bg-sunken disabled:text-muted";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx(CONTROL, "h-9", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(CONTROL, "h-9 pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

export function Textarea({
  className,
  mono = false,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { mono?: boolean }) {
  return (
    <textarea
      className={cx(CONTROL, "py-2 leading-relaxed", mono && "font-mono text-[13px]", className)}
      spellCheck={mono ? false : undefined}
      {...rest}
    />
  );
}

interface FieldProps {
  label: string;
  htmlFor: string;
  help?: ReactNode;
  error?: string | null;
  required?: boolean;
  children: ReactNode;
}

/** Label + control + help/error. Pass the same id to the control as `htmlFor`,
 * and `aria-describedby={`${id}-help`}` when help or an error is shown. */
export function Field({ label, htmlFor, help, error, required, children }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-ink">
        {label}
        {required && (
          <span className="ml-1 font-normal text-muted" aria-hidden="true">
            (required)
          </span>
        )}
      </label>
      {children}
      {(error || help) && (
        <p id={`${htmlFor}-help`} className={cx("text-xs", error ? "text-danger" : "text-muted")}>
          {error || help}
        </p>
      )}
    </div>
  );
}

export function Checkbox({
  label,
  description,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: string; description?: string }) {
  const id = useId();
  return (
    <div className="flex items-start gap-2.5">
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 h-4 w-4 rounded border-line-strong accent-accent"
        {...rest}
      />
      <label htmlFor={id} className="text-sm text-ink">
        {label}
        {description && <span className="block text-xs text-muted">{description}</span>}
      </label>
    </div>
  );
}

/** An on/off switch for enabling things in a list row. */
export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-55",
        checked ? "border-transparent bg-accent" : "border-line-strong bg-sunken",
      )}
    >
      <span
        className={cx(
          "inline-block h-3.5 w-3.5 rounded-full transition-transform",
          checked ? "translate-x-[18px] bg-on-accent" : "translate-x-0.5 bg-muted",
        )}
      />
    </button>
  );
}

// --- feedback --------------------------------------------------------------

export function Spinner({ small = false, label }: { small?: boolean; label?: string }) {
  return (
    <span
      role={label ? "status" : undefined}
      aria-label={label}
      className={cx(
        "inline-block animate-spin rounded-full border-2 border-current border-t-transparent opacity-70",
        small ? "h-3.5 w-3.5" : "h-5 w-5",
      )}
    />
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 px-1 py-10 text-sm text-muted" role="status">
      <Spinner />
      <span>{label}…</span>
    </div>
  );
}

export function ErrorNote({
  message,
  onRetry,
  className,
}: {
  message: string | null | undefined;
  onRetry?: () => void;
  className?: string;
}) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className={cx(
        "flex items-start justify-between gap-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2.5 text-sm text-danger",
        className,
      )}
    >
      <span className="break-words">{message}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="shrink-0 font-medium underline">
          Retry
        </button>
      )}
    </div>
  );
}

export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cx(
        "rounded-md border border-line bg-sunken px-3 py-2.5 text-sm text-muted",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong px-6 py-12 text-center">
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {children && <p className="mx-auto mt-1.5 max-w-md text-sm text-muted">{children}</p>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}

type Tone = "neutral" | "ok" | "warn" | "danger" | "accent";

const TONES: Record<Tone, string> = {
  neutral: "bg-sunken text-muted border-line",
  ok: "bg-ok-soft text-ok border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
  accent: "bg-accent-soft text-accent border-transparent",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  succeeded: "ok",
  ok: "ok",
  failed: "danger",
  error: "danger",
  running: "accent",
  queued: "warn",
  pending: "neutral",
  skipped: "neutral",
  untested: "neutral",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{status}</Badge>;
}

// --- layout ----------------------------------------------------------------

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-line bg-surface", className)}>
      {children}
    </section>
  );
}

export function CardHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      {actions}
    </div>
  );
}

/** Horizontally scrollable table wrapper so wide tables stay usable on narrow screens. */
export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full min-w-[560px] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-line text-xs tracking-wide text-muted uppercase">
            {head.map((cell, index) => (
              <th key={index} scope="col" className="px-4 py-2.5 font-medium">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&>tr:last-child]:border-0 [&>tr]:border-b [&>tr]:border-line">
          {children}
        </tbody>
      </table>
    </div>
  );
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cx("px-4 py-3 align-middle", className)}>{children}</td>;
}

export function CodeBlock({ children, label }: { children: string; label?: string }) {
  return (
    <pre
      aria-label={label}
      tabIndex={0}
      className="max-h-96 overflow-auto rounded-md border border-line bg-sunken p-3 font-mono text-[12.5px] leading-relaxed text-ink"
    >
      {children}
    </pre>
  );
}

// --- modal -----------------------------------------------------------------

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}

export function Modal({ title, onClose, children, wide = false }: ModalProps) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>(
      "input:not([type=hidden]), select, textarea, button:not([data-close])",
    );
    (first ?? panel.current)?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel.current) return;
      // Keep keyboard focus inside the dialog.
      const focusable = panel.current.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
      );
      const firstEl = focusable[0];
      const lastEl = focusable[focusable.length - 1];
      if (!firstEl || !lastEl) return;
      if (event.shiftKey && document.activeElement === firstEl) {
        event.preventDefault();
        lastEl.focus();
      } else if (!event.shiftKey && document.activeElement === lastEl) {
        event.preventDefault();
        firstEl.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/45 p-4 sm:p-8"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cx(
          "w-full rounded-lg border border-line bg-surface shadow-xl outline-none",
          wide ? "max-w-3xl" : "max-w-lg",
        )}
      >
        <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-3.5">
          <h2 id={titleId} className="text-base font-semibold text-ink">
            {title}
          </h2>
          <button
            type="button"
            data-close
            onClick={onClose}
            aria-label="Close"
            className="rounded-md px-2 py-1 text-lg leading-none text-muted hover:bg-sunken hover:text-ink"
          >
            ×
          </button>
        </div>
        <div className="px-5 py-5">{children}</div>
      </div>
    </div>
  );
}

export function FormActions({ children }: { children: ReactNode }) {
  return <div className="mt-6 flex flex-wrap justify-end gap-2">{children}</div>;
}

/** Confirmation for destructive actions. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel = "Delete",
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="space-y-4 text-sm text-muted">
        <div>{children}</div>
        <ErrorNote message={error} />
      </div>
      <FormActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="danger" busy={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </FormActions>
    </Modal>
  );
}
