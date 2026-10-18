import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  auth,
  setUnauthorizedHandler,
  tokenStore,
  workspaceApi,
  workspaces as workspacesApi,
  type User,
  type Workspace,
  type WorkspaceApi,
} from "../api";

const WORKSPACE_KEY = "anexa.workspace";

interface AuthState {
  /** "loading" while an existing token is being checked on startup. */
  status: "loading" | "signed-out" | "signed-in";
  user: User | null;
  workspaces: Workspace[];
  workspace: Workspace | null;
  /** Set when the stored session could not be verified for a reason other than 401. */
  startupError: string | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (input: {
    email: string;
    password: string;
    name: string;
    workspace_name?: string;
  }) => Promise<void>;
  logout: () => void;
  selectWorkspace: (id: string) => void;
  createWorkspace: (name: string) => Promise<Workspace>;
  retry: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

function readStoredWorkspace(): string | null {
  try {
    return localStorage.getItem(WORKSPACE_KEY);
  } catch {
    return null;
  }
}

function storeWorkspace(id: string | null) {
  try {
    if (id) localStorage.setItem(WORKSPACE_KEY, id);
    else localStorage.removeItem(WORKSPACE_KEY);
  } catch {
    /* storage unavailable */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthState["status"]>(
    tokenStore.get() ? "loading" : "signed-out",
  );
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(readStoredWorkspace);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const signOut = useCallback(() => {
    tokenStore.clear();
    setUser(null);
    setWorkspaces([]);
    setStatus("signed-out");
  }, []);

  const loadProfile = useCallback(async () => {
    const me = await auth.me();
    setUser(me.user);
    setWorkspaces(me.workspaces);
    setStatus("signed-in");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    return () => setUnauthorizedHandler(null);
  }, [signOut]);

  useEffect(() => {
    if (!tokenStore.get()) return;
    let cancelled = false;
    setStartupError(null);
    loadProfile().catch((cause: unknown) => {
      // A 401 already signed us out through the unauthorized handler.
      if (cancelled || !tokenStore.get()) return;
      setStartupError(cause instanceof Error ? cause.message : "Could not load your profile.");
    });
    return () => {
      cancelled = true;
    };
  }, [loadProfile, attempt]);

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await auth.login({ email, password });
      tokenStore.set(result.access_token);
      await loadProfile();
    },
    [loadProfile],
  );

  const signup = useCallback<AuthState["signup"]>(
    async (input) => {
      const result = await auth.signup(input);
      tokenStore.set(result.access_token);
      if (result.workspace) {
        storeWorkspace(result.workspace.id);
        setWorkspaceId(result.workspace.id);
      }
      await loadProfile();
    },
    [loadProfile],
  );

  const selectWorkspace = useCallback((id: string) => {
    storeWorkspace(id);
    setWorkspaceId(id);
  }, []);

  const createWorkspace = useCallback(
    async (name: string) => {
      const created = await workspacesApi.create(name);
      setWorkspaces((current) => [...current, created]);
      selectWorkspace(created.id);
      return created;
    },
    [selectWorkspace],
  );

  const workspace = useMemo(
    () => workspaces.find((ws) => ws.id === workspaceId) ?? workspaces[0] ?? null,
    [workspaces, workspaceId],
  );

  const value = useMemo<AuthState>(
    () => ({
      status,
      user,
      workspaces,
      workspace,
      startupError,
      login,
      signup,
      logout: signOut,
      selectWorkspace,
      createWorkspace,
      retry: () => setAttempt((n) => n + 1),
    }),
    [status, user, workspaces, workspace, startupError, login, signup, signOut, selectWorkspace, createWorkspace],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/** The signed-in user, or null when rendered outside the auth provider. */
export function useCurrentUser(): User | null {
  return useContext(AuthContext)?.user ?? null;
}

const WorkspaceContext = createContext<{ workspace: Workspace; api: WorkspaceApi } | null>(null);

/** Provides the current workspace and its API to every page inside the shell. */
export function WorkspaceProvider({
  workspace,
  children,
}: {
  workspace: Workspace;
  children: ReactNode;
}) {
  const value = useMemo(() => ({ workspace, api: workspaceApi(workspace.id) }), [workspace]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return value;
}
