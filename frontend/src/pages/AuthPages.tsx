import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import { errorMessage } from "../api";
import { useAuth } from "../auth/AuthContext";
import { Button, ErrorNote, Field, Input } from "../components/ui";

function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-7 flex items-center gap-2">
          <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M9 9L23 12L14 24Z" fill="none" stroke="var(--color-accent)" strokeWidth="2" />
            <circle cx="9" cy="9" r="5" fill="var(--color-accent)" />
            <circle cx="23" cy="12" r="4" fill="var(--color-accent)" />
            <circle cx="14" cy="24" r="4" fill="var(--color-accent)" />
          </svg>
          <span className="text-lg font-semibold tracking-tight">Orgraph</span>
        </div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 mb-6 text-sm text-muted">{subtitle}</p>
        {children}
        <p className="mt-6 text-sm text-muted">{footer}</p>
      </div>
    </main>
  );
}

const linkClass = "font-medium text-accent underline";

export function LoginPage() {
  const { status, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "signed-in") return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Run operators and explore your company graph."
      footer={
        <>
          New here?{" "}
          <Link to="/signup" className={linkClass}>
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate={false}>
        <Field label="Email" htmlFor="login-email">
          <Input
            id="login-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </Field>
        <Field label="Password" htmlFor="login-password">
          <Input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </Field>
        <ErrorNote message={error} />
        <Button type="submit" variant="primary" busy={busy} className="w-full">
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}

export function SignupPage() {
  const { status, signup } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "signed-in") return <Navigate to="/" replace />;

  const passwordError =
    password.length > 0 && password.length < 8 ? "Use at least 8 characters." : null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signup({
        name: name.trim(),
        email: email.trim(),
        password,
        ...(workspaceName.trim() ? { workspace_name: workspaceName.trim() } : {}),
      });
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Signing up also creates a workspace that you own."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className={linkClass}>
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="Your name" htmlFor="signup-name">
          <Input
            id="signup-name"
            autoComplete="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </Field>
        <Field label="Email" htmlFor="signup-email">
          <Input
            id="signup-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </Field>
        <Field
          label="Password"
          htmlFor="signup-password"
          help="At least 8 characters."
          error={passwordError}
        >
          <Input
            id="signup-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby="signup-password-help"
            aria-invalid={passwordError ? true : undefined}
            required
          />
        </Field>
        <Field
          label="Workspace name"
          htmlFor="signup-workspace"
          help="Optional. Defaults to a workspace named after you."
        >
          <Input
            id="signup-workspace"
            value={workspaceName}
            onChange={(event) => setWorkspaceName(event.target.value)}
            aria-describedby="signup-workspace-help"
            placeholder="Acme"
          />
        </Field>
        <ErrorNote message={error} />
        <Button type="submit" variant="primary" busy={busy} className="w-full">
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}
