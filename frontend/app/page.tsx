"use client";

import { useEffect, useState, type ReactNode } from "react";
import "./styles.css";

type Role = "OWNER" | "ADMIN" | "MEMBER" | "VIEWER";
type Ecosystem = "python" | "node";
type Project = {
  id: string;
  name: string;
  organization_id: string;
  repository?: string | null;
  default_ecosystem: Ecosystem;
  active: boolean;
  auto_verify_pull_requests: boolean;
  github_installation_id?: number | null;
  review_network_additions: boolean;
  review_process_additions: boolean;
  max_file_delta: number;
  block_on_test_failure: boolean;
  runtime_regression_review_percent: number;
  runtime_regression_block_percent: number;
  runtime_regression_min_ms: number;
};
type Run = {
  id: string;
  project_id: string;
  package_name: string;
  ecosystem: string;
  old_version: string;
  new_version: string;
  smoke_import?: string | null;
  status: string;
  decision?: string | null;
  severity?: string | null;
  summary?: string | null;
  result_json?: any;
  ai_explanation?: string | null;
  source: string;
  github_repo?: string | null;
  github_pr?: number | null;
  github_sha?: string | null;
  github_check_run_id?: number | null;
  github_comment_id?: number | null;
  ai_status: string;
  ai_attempts: number;
  ai_error?: string | null;
  created_at: string;
  finished_at?: string | null;
};
type Stats = { total: number; pass_count: number; review_count: number; block_count: number; running_count: number };
type Integrations = {
  kubernetes: boolean;
  ai_enabled: boolean;
  ai_configured: boolean;
  ai_model: string;
  github_configured: boolean;
  github_app_url?: string | null;
  github_webhook_url?: string | null;
  github_check_name: string;
  stripe_configured: boolean;
};
type OrgContext = {
  user: { id: string; email: string; name: string };
  current: { organization_id: string | null; role: Role | null };
  organizations: { id: string; name: string; slug: string; plan_code: string; role: Role }[];
};
type Member = { membership_id: string; user_id: string; email: string; name: string; role: Role; status: string; created_at: string };
type Usage = { plan_code: string; limits: { verification_runs: number; ai_explanations: number; projects: number }; verification_runs: number; ai_explanations: number; projects: number; period_start: string };
type Billing = {
  organization_id: string;
  plan_code: string;
  subscription_status: string;
  stripe_customer_id?: string | null;
  stripe_subscription_id?: string | null;
  cancel_at_period_end: boolean;
  current_period_end?: string | null;
  usage: { verification_runs: number; ai_explanations: number };
  limits: Record<string, number>;
};
type GHStatus = { configured: boolean; app_id?: string | null; app_slug?: string | null; installation_url?: string | null; setup_url?: string | null; webhook_url?: string | null; events: string[]; supported_actions: string[]; check_name: string };
type GHInstallation = { installation_id: number; organization_id?: string | null; account_login?: string | null; account_type?: string | null; suspended_at?: string | null; deleted_at?: string | null };
type Audit = { id: string; actor_user_id?: string | null; event_type: string; resource_type?: string | null; resource_id?: string | null; details: any; created_at: string };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  headers.set("Content-Type", "application/json");
  const storedOrg = typeof window !== "undefined" ? localStorage.getItem("dcv-org-id") : null;
  const actor = typeof window !== "undefined" ? localStorage.getItem("dcv-actor-email") : null;
  if (storedOrg) headers.set("X-Dcv-Organization-Id", storedOrg);
  if (actor) headers.set("X-Dcv-Actor-Email", actor);

  const request = (h: Headers) => fetch(path, { ...options, headers: h, cache: "no-store" });
  let response = await request(headers);
  if (!response.ok) {
    let detail = "Request failed";
    try {
      const body = await response.clone().json();
      detail = body.detail || body.message || detail;
    } catch {
      try { detail = (await response.clone().text()) || detail; } catch {}
    }
    if (storedOrg && ((response.status === 404 && detail === "Organization not found") || (response.status === 403 && detail === "User is not a member of this organization"))) {
      localStorage.removeItem("dcv-org-id");
      const retry = new Headers(options?.headers);
      retry.set("Content-Type", "application/json");
      if (actor) retry.set("X-Dcv-Actor-Email", actor);
      response = await request(retry);
      if (response.ok) return response.json();
    }
    throw new Error(detail);
  }
  return response.json();
}

const canAdmin = (role?: Role) => role === "OWNER" || role === "ADMIN";
const canRun = (role?: Role) => role === "OWNER" || role === "ADMIN" || role === "MEMBER";

export default function Home() {
  const [tab, setTab] = useState<"overview" | "projects" | "github" | "admin" | "billing">("overview");
  const [ctx, setCtx] = useState<OrgContext | null>(null);
  const [orgId, setOrgId] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [stats, setStats] = useState<Stats>({ total: 0, pass_count: 0, review_count: 0, block_count: 0, running_count: 0 });
  const [integrations, setIntegrations] = useState<Integrations | null>(null);
  const [gh, setGh] = useState<GHStatus | null>(null);
  const [installations, setInstallations] = useState<GHInstallation[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [billing, setBilling] = useState<Billing | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [selected, setSelected] = useState<Run | null>(null);
  const [projectId, setProjectId] = useState("");
  const [packageName, setPackageName] = useState("requests");
  const [oldVersion, setOldVersion] = useState("2.31.0");
  const [newVersion, setNewVersion] = useState("2.32.4");
  const [ecosystem, setEcosystem] = useState<Ecosystem>("python");
  const [smokeImport, setSmokeImport] = useState("requests");
  const [newProject, setNewProject] = useState({ name: "", repository: "", ecosystem: "python" as Ecosystem });
  const [orgForm, setOrgForm] = useState({ name: "", billing_email: "" });
  const [orgCreate, setOrgCreate] = useState({ name: "", slug: "" });
  const [invite, setInvite] = useState({ email: "", role: "MEMBER" });
  const [identity, setIdentity] = useState("");
  const [loading, setLoading] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [inviteAccepting, setInviteAccepting] = useState(false);

  const loadContext = async () => {
    const c = await api<OrgContext>("/api/admin/context");
    setCtx(c);
    if (c.current.organization_id) {
      setOrgId(c.current.organization_id);
      setProjectId(prev => prev || "");
      localStorage.setItem("dcv-org-id", c.current.organization_id);
      localStorage.setItem("dcv-actor-email", c.user.email);
      setIdentity(c.user.email);
      const current = c.organizations.find(o => o.id === c.current.organization_id);
      if (current) setOrgForm(prev => ({ ...prev, name: current.name }));
    }
  };

  const refresh = async () => {
    try {
      const [p, r, s] = await Promise.all([
        api<Project[]>("/api/projects"),
        api<Run[]>("/api/verifications"),
        api<Stats>("/api/stats"),
      ]);
      setProjects(p);
      setRuns(r);
      setStats(s);
      setProjectId(current => current && p.some(x => x.id === current) ? current : p[0]?.id || "");
      if (selected) setSelected(r.find(x => x.id === selected.id) || null);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load platform data");
      return;
    }
    const optional: Promise<any>[] = [
      api<Integrations>("/api/integrations"),
      api<GHStatus>("/api/github/status"),
      api<GHInstallation[]>("/api/github/installations"),
      api<Member[]>("/api/admin/members"),
      api<Usage>("/api/admin/usage"),
      api<Billing>("/api/billing"),
      api<Audit[]>("/api/admin/audit?limit=30"),
    ];
    const settled = await Promise.allSettled(optional);
    if (settled[0].status === "fulfilled") setIntegrations(settled[0].value);
    if (settled[1].status === "fulfilled") setGh(settled[1].value);
    if (settled[2].status === "fulfilled") setInstallations(settled[2].value);
    if (settled[3].status === "fulfilled") setMembers(settled[3].value);
    if (settled[4].status === "fulfilled") setUsage(settled[4].value);
    if (settled[5].status === "fulfilled") setBilling(settled[5].value);
    if (settled[6].status === "fulfilled") setAudit(settled[6].value);
  };

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("invite");
    if (token) setInviteToken(token);
    loadContext().catch(e => setError(e instanceof Error ? e.message : "Unable to load organization context"));
  }, []);
  useEffect(() => {
    if (!orgId) return;
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [orgId]);

  const activeProject = projects.find(p => p.id === projectId) || projects[0];
  const currentRole: Role | undefined = ctx?.current.role ?? undefined;
  const admin = canAdmin(currentRole);
  const member = canRun(currentRole);

  const runVerification = async () => {
    if (!projectId) { setError("Select a project before running a verification"); return; }
    setLoading(true); setError(""); setNotice("");
    try {
      const run = await api<Run>("/api/verifications", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId, package_name: packageName.trim(), ecosystem, old_version: oldVersion.trim(), new_version: newVersion.trim(), smoke_import: smokeImport.trim() || null }),
      });
      setSelected(run);
      setNotice("Verification started. The dashboard will update as Kubernetes evidence arrives.");
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Verification failed"); }
    finally { setLoading(false); }
  };

  const explain = async () => {
    if (!selected) return;
    setAiLoading(true); setError("");
    try {
      const result = await api<{ explanation: string }>(`/api/verifications/${selected.id}/explain`, { method: "POST", body: "{}" });
      setSelected({ ...selected, ai_explanation: result.explanation });
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "AI explanation failed"); }
    finally { setAiLoading(false); }
  };

  const createProject = async () => {
    try {
      await api<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name: newProject.name, repository: newProject.repository || null, default_ecosystem: newProject.ecosystem }) });
      setNewProject({ name: "", repository: "", ecosystem: "python" });
      setNotice("Project created"); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Project creation failed"); }
  };

  const saveProject = async (patch: Partial<Project>) => {
    if (!activeProject) return;
    try { await api<Project>(`/api/projects/${activeProject.id}`, { method: "PATCH", body: JSON.stringify(patch) }); setNotice("Project policy updated"); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to update project"); }
  };

  const createOrg = async () => {
    try {
      const created = await api<{ id: string; name: string }>("/api/admin/organizations", { method: "POST", body: JSON.stringify(orgCreate) });
      setOrgCreate({ name: "", slug: "" });
      setNotice(`Organization created: ${created.name}`); await loadContext();
      setOrgId(created.id); localStorage.setItem("dcv-org-id", created.id); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to create organization"); }
  };

  const saveOrg = async () => {
    try { await api("/api/admin/organization", { method: "PATCH", body: JSON.stringify(orgForm) }); setNotice("Organization saved"); await loadContext(); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to save organization"); }
  };

  const sendInvite = async () => {
    try {
      const result = await api<{ invite_url: string }>("/api/admin/invitations", { method: "POST", body: JSON.stringify(invite) });
      setInvite({ email: "", role: "MEMBER" }); setNotice(`Invitation created: ${result.invite_url}`); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Invitation failed"); }
  };

  const updateMember = async (m: Member, role: Role, status: string) => {
    try { await api(`/api/admin/members/${m.membership_id}`, { method: "PATCH", body: JSON.stringify({ role, status }) }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Member update failed"); }
  };

  const checkout = async (plan: "TEAM" | "BUSINESS") => {
    try { const result = await api<{ url: string }>("/api/billing/checkout", { method: "POST", body: JSON.stringify({ plan }) }); window.location.href = result.url; }
    catch (e) { setError(e instanceof Error ? e.message : "Stripe checkout unavailable"); }
  };
  const portal = async () => {
    try { const result = await api<{ url: string }>("/api/billing/portal", { method: "POST", body: "{}" }); window.location.href = result.url; }
    catch (e) { setError(e instanceof Error ? e.message : "Billing portal unavailable"); }
  };
  const testGithub = async () => {
    try { const result = await api<any>("/api/github/test", { method: "POST", body: "{}" }); setNotice(`GitHub App connected: ${result.name || result.slug}`); }
    catch (e) { setError(e instanceof Error ? e.message : "GitHub test failed"); }
  };
  const testAI = async () => {
    try { const result = await api<any>("/api/ai/test", { method: "POST", body: "{}" }); setNotice(result.message); }
    catch (e) { setError(e instanceof Error ? e.message : "AI test failed"); }
  };
  const attach = async (id: number) => {
    try { await api(`/api/github/installations/${id}/attach`, { method: "POST", body: "{}" }); setNotice("GitHub installation attached"); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to attach installation"); }
  };
  const acceptInvite = async () => {
    if (!inviteToken) return;
    setInviteAccepting(true); setError("");
    try {
      const result = await api<{ accepted: boolean; organization_id: string; role: Role }>(`/api/admin/invitations/${encodeURIComponent(inviteToken)}/accept`, { method: "POST", body: "{}" });
      localStorage.setItem("dcv-org-id", result.organization_id);
      setOrgId(result.organization_id);
      setInviteToken(null);
      setNotice(`Invitation accepted as ${result.role.toLowerCase()}.`);
      window.history.replaceState({}, document.title, window.location.pathname);
      await loadContext();
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Invitation acceptance failed"); }
    finally { setInviteAccepting(false); }
  };

  const saveIdentity = () => {
    const value = identity.trim().toLowerCase();
    if (!value.includes("@")) { setError("Enter a valid development identity email"); return; }
    localStorage.setItem("dcv-actor-email", value);
    localStorage.removeItem("dcv-org-id");
    setNotice(`Development identity set to ${value}`);
    window.location.reload();
  };

  const installUrl = gh?.installation_url && orgId ? `${gh.installation_url}?state=${encodeURIComponent(orgId)}` : null;
  const limit = (key: keyof Usage["limits"]) => {
    const value = usage?.limits?.[key] ?? 0;
    return value < 0 ? "∞" : String(value);
  };
  const comparison = selected?.result_json?.comparison || {};
  const deltas = comparison.deltas || {};

  return (
    <main className="app-shell">{inviteToken&&<div className="banner"><strong>Organization invitation</strong><span>Accept this invitation using the current development identity ({identity || "unknown"}).</span><button className="secondary-btn" onClick={acceptInvite} disabled={inviteAccepting}>{inviteAccepting?"Accepting…":"Accept invitation"}</button></div>}
      <aside className="sidebar">
        <div className="brand-mark"><span>DV</span><div><strong>Dependency Verification</strong><small>Change intelligence platform</small></div></div>
        <nav>{(["overview", "projects", "github", "admin", "billing"] as const).map(id => {
          const labels = { overview: "Overview", projects: "Projects", github: "GitHub & AI", admin: "Administration", billing: "Billing" };
          return <button key={id} className={tab === id ? "nav active" : "nav"} onClick={() => setTab(id)}>{labels[id]}</button>;
        })}</nav>
        <div className="sidebar-foot">DCV 15.0 · GitHub · CI/CD · Kubernetes · Argo CD · AI · SaaS</div>
      </aside>

      <section className="main-content">
        <header className="topbar">
          <div><div className="eyebrow">DEPENDENCY CHANGE VERIFICATION</div><h1>Know what changed before it reaches production.</h1><p>Behavioral evidence, deterministic gates, GitHub Checks, and optional AI explanation for dependency upgrades.</p></div>
          <div className="project-switcher"><label>Organization</label><select value={orgId} onChange={e => { setOrgId(e.target.value); localStorage.setItem("dcv-org-id", e.target.value); }}><option value="">Loading organization…</option>{ctx?.organizations.map(o => <option key={o.id} value={o.id}>{o.name} · {o.plan_code} · {o.role}</option>)}</select></div>
        </header>

        {error && <div className="alert">{error}</div>}
        {notice && <div className="notice">{notice}</div>}
        {ctx && !orgId && <section className="card"><div className="section-head"><div><div className="eyebrow">ACCOUNT ONBOARDING</div><h2>Create your first organization</h2><p>This account does not have an active organization yet. Create one in Administration to begin adding projects and verification runs.</p></div><button className="primary-btn" onClick={() => setTab("admin")}>Open Administration</button></div></section>}

        {tab === "overview" && <>
          <div className="stats-grid"><Stat label="Total runs" value={stats.total}/><Stat label="Passed" value={stats.pass_count} tone="good"/><Stat label="Needs review" value={stats.review_count} tone="warn"/><Stat label="Blocked" value={stats.block_count} tone="bad"/></div>
          <div className="workspace-grid">
            <section className="card verify-card">
              <div className="section-head"><div><h2>Run a verification</h2><p>Manual verification and GitHub PR automation share the same deterministic evidence engine.</p></div><span className="pill">{activeProject?.default_ecosystem || ecosystem}</span></div>
              <div className="form-grid"><Field label="Project"><select value={projectId} onChange={e => setProjectId(e.target.value)}>{projects.length === 0 && <option value="">Create a project first</option>}{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field><Field label="Package"><input value={packageName} onChange={e => setPackageName(e.target.value)}/></Field><Field label="Ecosystem"><select value={ecosystem} onChange={e => setEcosystem(e.target.value as Ecosystem)}><option value="python">Python</option><option value="node">Node.js</option></select></Field><Field label="Previous version"><input value={oldVersion} onChange={e => setOldVersion(e.target.value)}/></Field><Field label="New version"><input value={newVersion} onChange={e => setNewVersion(e.target.value)}/></Field><Field label="Smoke import / require"><input value={smokeImport} onChange={e => setSmokeImport(e.target.value)} /></Field></div>
              <button className="primary-btn" onClick={runVerification} disabled={loading || !member || !projectId}>{loading ? "Starting…" : member ? "Run verification" : "Viewer access is read-only"}</button>
              <div className="measure-grid"><Measure title="Old vs new" desc="Isolated execution"/><Measure title="Observable evidence" desc="Files · process · network"/><Measure title="Decision engine" desc="PASS · REVIEW · BLOCK"/><Measure title="AI layer" desc="Evidence-only explanation"/></div>
            </section>
            <section className="card"><div className="section-head"><div><h2>Verification history</h2><p>{runs.length} runs in this organization.</p></div></div><div className="run-list">{runs.map(run => <button key={run.id} className={`run-item ${selected?.id === run.id ? "selected" : ""}`} onClick={() => setSelected(run)}><div><strong>{run.package_name}</strong><small>{run.old_version} → {run.new_version} · {run.source}</small></div><Decision value={run.decision || run.status} severity={run.severity}/></button>)}{runs.length === 0 && <div className="empty">No verification runs yet.</div>}</div></section>
          </div>
          {selected && <section className="card detail-card"><div className="section-head"><div><div className="eyebrow">RUN DETAIL</div><h2>{selected.package_name} <span>{selected.old_version} → {selected.new_version}</span></h2><p>{selected.summary || "Verification is running in Kubernetes."}</p></div><Decision value={selected.decision || selected.status} severity={selected.severity}/></div>{selected.result_json ? <><div className="evidence-grid"><Evidence label="Behavior score" value={comparison.score ?? "—"}/><Evidence label="New network" value={deltas.network_count_delta ?? 0}/><Evidence label="New processes" value={deltas.process_count_delta ?? 0}/><Evidence label="File delta" value={deltas.file_count_delta ?? 0}/><Evidence label="Transitive changes" value={deltas.dependency_version_change_count ?? 0}/><Evidence label="Runtime regression" value={deltas.smoke_regression_percent == null ? "—" : `${deltas.smoke_regression_percent}%`}/></div><div className="detail-columns"><div><h3>Evidence bundle</h3><pre>{JSON.stringify(selected.result_json, null, 2)}</pre></div><div><h3>AI explanation</h3>{selected.ai_explanation ? <div className="ai-box">{selected.ai_explanation}</div> : <><p className="muted">Status: {selected.ai_status}</p><button className="secondary-btn" onClick={explain} disabled={aiLoading || selected.ai_status === "RUNNING" || !integrations?.ai_configured}>{aiLoading ? "Analyzing…" : "Explain with AI"}</button>{selected.ai_error && <p className="muted">{selected.ai_error}</p>}</>}</div></div></> : <div className="empty">Verification is running in a Kubernetes Job.</div>}</section>}
        </>}

        {tab === "projects" && <ProjectsView projects={projects} active={activeProject} admin={admin} newProject={newProject} setNewProject={setNewProject} createProject={createProject} saveProject={saveProject}/>} 
        {tab === "github" && <GitHubView integrations={integrations} gh={gh} installations={installations} installUrl={installUrl} admin={admin} testGithub={testGithub} testAI={testAI} attach={attach}/>} 
        {tab === "admin" && <AdminView ctx={ctx} admin={admin} orgForm={orgForm} setOrgForm={setOrgForm} saveOrg={saveOrg} orgCreate={orgCreate} setOrgCreate={setOrgCreate} createOrg={createOrg} members={members} updateMember={updateMember} invite={invite} setInvite={setInvite} sendInvite={sendInvite} usage={usage} audit={audit} identity={identity} setIdentity={setIdentity} saveIdentity={saveIdentity}/>} 
        {tab === "billing" && <BillingView billing={billing} stripeConfigured={integrations?.stripe_configured || false} admin={admin} checkout={checkout} portal={portal}/>} 
      </section>
    </main>
  );
}

function ProjectsView({projects, active, admin, newProject, setNewProject, createProject, saveProject}:{projects:Project[];active?:Project;admin:boolean;newProject:{name:string;repository:string;ecosystem:Ecosystem};setNewProject:(x:{name:string;repository:string;ecosystem:Ecosystem})=>void;createProject:()=>void;saveProject:(patch:Partial<Project>)=>void}) {
  return <div className="projects-layout"><section className="card"><div className="section-head"><div><h2>Projects</h2><p>Each project owns the repository mapping and deterministic policy used by its verification runs.</p></div></div><div className="project-list">{projects.map(p=><button key={p.id} className={`project-item ${active?.id===p.id?"selected":""}`} onClick={()=>{}}><div><strong>{p.name}</strong><small>{p.repository||"No repository connected"}</small></div><span className="pill">{p.default_ecosystem}</span></button>)}{projects.length===0&&<div className="empty">No projects yet.</div>}</div></section><section className="card"><h2>Create project</h2><p className="muted">Projects are organization-scoped. Only owners and administrators can create or change them.</p><div className="form-stack"><Field label="Name"><input value={newProject.name} onChange={e=>setNewProject({...newProject,name:e.target.value})} placeholder="Payments API" disabled={!admin}/></Field><Field label="Repository"><input value={newProject.repository} onChange={e=>setNewProject({...newProject,repository:e.target.value})} placeholder="https://github.com/acme/payments" disabled={!admin}/></Field><Field label="Ecosystem"><select value={newProject.ecosystem} onChange={e=>setNewProject({...newProject,ecosystem:e.target.value as Ecosystem})} disabled={!admin}><option value="python">Python</option><option value="node">Node.js</option></select></Field><button className="primary-btn" onClick={createProject} disabled={!admin || !newProject.name.trim()}>Create project</button></div></section>{active&&<section className="card"><div className="section-head"><div><h2>Verification policy</h2><p>{active.repository||active.name}</p></div><span className="pill">{active.active?"Active":"Inactive"}</span></div><div className="policy-grid"><PolicyToggle label="Automatically verify GitHub PR dependency changes" checked={active.auto_verify_pull_requests} disabled={!admin} onChange={v=>saveProject({auto_verify_pull_requests:v})}/><PolicyToggle label="Review new network endpoints" checked={active.review_network_additions} disabled={!admin} onChange={v=>saveProject({review_network_additions:v})}/><PolicyToggle label="Review new process behavior" checked={active.review_process_additions} disabled={!admin} onChange={v=>saveProject({review_process_additions:v})}/><PolicyToggle label="Block failed install/smoke tests" checked={active.block_on_test_failure} disabled={!admin} onChange={v=>saveProject({block_on_test_failure:v})}/><Field label="Max file delta"><input type="number" min={0} max={1000} value={active.max_file_delta} onChange={e=>saveProject({max_file_delta:Number(e.target.value)})} disabled={!admin}/></Field><Field label="Runtime review threshold (%)"><input type="number" min={0} max={1000} value={active.runtime_regression_review_percent} onChange={e=>saveProject({runtime_regression_review_percent:Number(e.target.value)})} disabled={!admin}/></Field><Field label="Runtime block threshold (%)"><input type="number" min={0} max={5000} value={active.runtime_regression_block_percent} onChange={e=>saveProject({runtime_regression_block_percent:Number(e.target.value)})} disabled={!admin}/></Field><Field label="Minimum runtime delta (ms)"><input type="number" min={0} max={600000} value={active.runtime_regression_min_ms} onChange={e=>saveProject({runtime_regression_min_ms:Number(e.target.value)})} disabled={!admin}/></Field></div></section>}</div>;
}

function GitHubView({integrations,gh,installations,installUrl,admin,testGithub,testAI,attach}:{integrations:Integrations|null;gh:GHStatus|null;installations:GHInstallation[];installUrl:string|null;admin:boolean;testGithub:()=>void;testAI:()=>void;attach:(id:number)=>void}) {
  return <div className="projects-layout"><section className="card"><div className="section-head"><div><h2>GitHub App & Checks</h2><p>Signed webhook → durable queue → dependency diff → Kubernetes verification → one Check Run per dependency.</p></div><span className={gh?.configured?"integration on":"integration"}>{gh?.configured?"Configured":"Needs credentials"}</span></div><div className="integration-detail"><p><strong>Webhook:</strong> {gh?.webhook_url||"Configure GITHUB_APP_* and APP_PUBLIC_URL"}</p><p><strong>Post-install setup:</strong> {gh?.setup_url||"Not configured"}</p><p><strong>Events:</strong> {gh?.events?.join(", ")||"—"}</p><p><strong>Check:</strong> {gh?.check_name||"Dependency Change Verification"}</p></div><div className="button-row"><button className="secondary-btn" onClick={testGithub} disabled={!admin || !gh?.configured}>Test GitHub App</button>{installUrl&&<a className="secondary-btn" href={installUrl} target="_blank" rel="noreferrer">Install App for this organization</a>}</div></section><section className="card"><h2>Connected installations</h2><p className="muted">Only installations already attached to this organization are displayed.</p>{installations.map(i=><div className="admin-row" key={i.installation_id}><div><strong>{i.account_login||"Unknown account"}</strong><small>Installation {i.installation_id} · {i.account_type||"account"}</small></div><span className="pill">Attached</span></div>)}{installations.length===0&&<div className="empty">No installation is attached yet. Use the organization-specific install link above.</div>}</section><section className="card"><h2>AI explanation layer</h2><p>AI is downstream of the deterministic gate. It explains supplied evidence and cannot change PASS / REVIEW / BLOCK.</p><div className="integration-detail"><p><strong>Provider:</strong> {integrations?.ai_configured?"Connected":"Not configured"}</p><p><strong>Model:</strong> {integrations?.ai_model||"—"}</p><p><strong>Automatic explanation:</strong> {integrations?.ai_enabled?"Enabled":"Disabled"}</p></div><button className="secondary-btn" onClick={testAI} disabled={!admin || !integrations?.ai_configured}>Test AI connection</button></section></div>;
}

function AdminView({ctx,admin,orgForm,setOrgForm,saveOrg,orgCreate,setOrgCreate,createOrg,members,updateMember,invite,setInvite,sendInvite,usage,audit,identity,setIdentity,saveIdentity}:{ctx:OrgContext|null;admin:boolean;orgForm:{name:string;billing_email:string};setOrgForm:(x:{name:string;billing_email:string})=>void;saveOrg:()=>void;orgCreate:{name:string;slug:string};setOrgCreate:(x:{name:string;slug:string})=>void;createOrg:()=>void;members:Member[];updateMember:(m:Member,r:Role,s:string)=>void;invite:{email:string;role:string};setInvite:(x:{email:string;role:string})=>void;sendInvite:()=>void;usage:Usage|null;audit:Audit[];identity:string;setIdentity:(v:string)=>void;saveIdentity:()=>void}) {
  const limit = (key:keyof Usage["limits"]) => { const value = usage?.limits?.[key] ?? 0; return value < 0 ? "∞" : String(value); };
  return <div className="projects-layout"><section className="card"><h2>Organization administration</h2><p>Tenant-scoped members, projects, usage, invitations and audit history.</p><div className="form-grid"><Field label="Create organization"><input value={orgCreate.name} onChange={e=>setOrgCreate({...orgCreate,name:e.target.value})} placeholder="Acme Engineering"/></Field><Field label="Slug"><input value={orgCreate.slug} onChange={e=>setOrgCreate({...orgCreate,slug:e.target.value})} placeholder="acme-engineering"/></Field></div><button className="secondary-btn" onClick={createOrg}>Create organization</button><div className="form-stack"><Field label="Organization name"><input value={orgForm.name} onChange={e=>setOrgForm({...orgForm,name:e.target.value})} disabled={!admin}/></Field><Field label="Billing email"><input value={orgForm.billing_email} onChange={e=>setOrgForm({...orgForm,billing_email:e.target.value})} disabled={!admin}/></Field><button className="primary-btn" onClick={saveOrg} disabled={!admin}>Save organization</button></div></section><section className="card"><div className="section-head"><div><h2>Members</h2><p>Your role: {ctx?.current.role||"—"}</p></div></div>{members.map(m=><div className="admin-row" key={m.membership_id}><div><strong>{m.name}</strong><small>{m.email}</small></div>{admin?<div className="button-row"><select value={m.role} onChange={e=>updateMember(m,e.target.value as Role,m.status)}><option>OWNER</option><option>ADMIN</option><option>MEMBER</option><option>VIEWER</option></select><select value={m.status} onChange={e=>updateMember(m,m.role,e.target.value)}><option>ACTIVE</option><option>SUSPENDED</option></select></div>:<span className="pill">{m.role} · {m.status}</span>}</div>)}</section><section className="card"><h2>Invite member</h2><div className="form-grid"><Field label="Email"><input value={invite.email} onChange={e=>setInvite({...invite,email:e.target.value})} disabled={!admin}/></Field><Field label="Role"><select value={invite.role} onChange={e=>setInvite({...invite,role:e.target.value})} disabled={!admin}><option>MEMBER</option><option>ADMIN</option><option>VIEWER</option></select></Field></div><button className="secondary-btn" onClick={sendInvite} disabled={!admin||!invite.email}>Create invitation</button></section><section className="card"><h2>Usage</h2><div className="evidence-grid"><Evidence label="Plan" value={usage?.plan_code||"—"}/><Evidence label="Runs this month" value={`${usage?.verification_runs||0} / ${limit("verification_runs")}`}/><Evidence label="AI explanations" value={`${usage?.ai_explanations||0} / ${limit("ai_explanations")}`}/><Evidence label="Projects" value={`${usage?.projects||0} / ${limit("projects")}`}/></div></section><section className="card"><h2>Audit log</h2>{audit.length===0?<div className="empty">No audit entries yet.</div>:<div className="audit-list">{audit.map(a=><div key={a.id}><strong>{a.event_type}</strong><small>{new Date(a.created_at).toLocaleString()} · {a.resource_type||"system"}</small></div>)}</div>}</section><section className="card"><h2>Development identity</h2><p className="muted">This control exists only for the intentionally deferred production authentication layer.</p><div className="form-grid"><Field label="X-Dcv-Actor-Email"><input value={identity} onChange={e=>setIdentity(e.target.value)} placeholder="owner@local.dcv"/></Field></div><button className="secondary-btn" onClick={saveIdentity}>Apply development identity</button></section></div>;
}

function BillingView({billing,stripeConfigured,admin,checkout,portal}:{billing:Billing|null;stripeConfigured:boolean;admin:boolean;checkout:(p:"TEAM"|"BUSINESS")=>void;portal:()=>void}) {
  return <div className="projects-layout"><section className="card"><div className="section-head"><div><h2>Billing & entitlements</h2><p>Stripe Checkout handles recurring subscription purchase and the hosted portal handles ongoing billing changes.</p></div><span className="pill">{billing?.plan_code||"FREE"}</span></div><div className="evidence-grid"><Evidence label="Subscription" value={billing?.subscription_status||"inactive"}/><Evidence label="Runs used" value={billing?.usage.verification_runs||0}/><Evidence label="AI used" value={billing?.usage.ai_explanations||0}/><Evidence label="Cancel at period end" value={billing?.cancel_at_period_end?"Yes":"No"}/></div>{billing?.stripe_subscription_id&&<button className="secondary-btn" onClick={portal} disabled={!admin}>Manage billing</button>}</section><section className="card"><h2>Plans</h2><div className="plan-grid"><PlanCard code="FREE" limits={{verification_runs:50,ai_explanations:25,projects:3}} current={billing?.plan_code==="FREE"}/><PlanCard code="TEAM" limits={{verification_runs:1000,ai_explanations:2000,projects:25}} current={billing?.plan_code==="TEAM"} action={stripeConfigured&&admin?()=>checkout("TEAM"):undefined}/><PlanCard code="BUSINESS" limits={{verification_runs:10000,ai_explanations:20000,projects:100}} current={billing?.plan_code==="BUSINESS"} action={stripeConfigured&&admin?()=>checkout("BUSINESS"):undefined}/><PlanCard code="ENTERPRISE" limits={{verification_runs:-1,ai_explanations:-1,projects:-1}} current={billing?.plan_code==="ENTERPRISE"}/></div>{!stripeConfigured&&<p className="muted">Stripe is not configured. Add STRIPE_SECRET_KEY, STRIPE_PRICE_TEAM and STRIPE_PRICE_BUSINESS.</p>}</section></div>;
}

function PlanCard({code,limits,current,action}:{code:string;limits:Record<string,number>;current:boolean;action?:()=>void}){return <div className={`plan-card ${current?"current":""}`}><strong>{code}</strong><span>{limits.verification_runs<0?"Unlimited":limits.verification_runs} verification runs / month</span><span>{limits.ai_explanations<0?"Unlimited":limits.ai_explanations} AI explanations / month</span><span>{limits.projects<0?"Unlimited":limits.projects} projects</span>{current?<span className="pill">Current</span>:action&&<button className="secondary-btn" onClick={action}>Choose {code}</button>}</div>}
function Stat({label,value,tone}:{label:string;value:number;tone?:string}){return <div className={`stat-card ${tone||""}`}><span>{label}</span><strong>{value}</strong></div>}
function Field({label,children}:{label:string;children:ReactNode}){return <label className="field"><span>{label}</span>{children}</label>}
function Measure({title,desc}:{title:string;desc:string}){return <div className="measure"><div className="measure-icon">✓</div><div><strong>{title}</strong><span>{desc}</span></div></div>}
function PolicyToggle({label,checked,disabled,onChange}:{label:string;checked:boolean;disabled:boolean;onChange:(value:boolean)=>void}){return <label><input type="checkbox" checked={checked} disabled={disabled} onChange={e=>onChange(e.target.checked)}/>{label}</label>}
function Decision({value,severity}:{value:string;severity?:string|null}){return <span className={`decision ${value.toLowerCase()}`}>{value}{severity&&value!=="RUNNING"&&<small>{severity}</small>}</span>}
function Evidence({label,value}:{label:string;value:string|number}){return <div className="evidence"><span>{label}</span><strong>{value}</strong></div>}
