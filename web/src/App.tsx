import { useState } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { KeyRound, Sparkles } from "lucide-react";
import { AuthError, setToken, useApi } from "./lib/api";
import type { Meta } from "./lib/types";
import { Button, MetaCtx, Skeleton } from "./components/ui";
import { CommandPalette, JobProvider, Sidebar, ToastProvider, Topbar } from "./components/shell";
import Overview from "./pages/Overview";
import Signals from "./pages/Signals";
import { CompetitorDetailPage, CompetitorList } from "./pages/Competitors";
import Content from "./pages/Content";
import AiVisibility from "./pages/AiVisibility";
import Digest from "./pages/Digest";
import Settings from "./pages/Settings";

export default function App() {
  const { data: meta, error } = useApi<Meta>("/api/meta");
  if (error instanceof AuthError) return <Login />;
  if (!meta) return <Boot error={error} />;
  return (
    <MetaCtx.Provider value={meta}>
      <BrowserRouter>
        <ToastProvider>
          <JobProvider>
            <Layout meta={meta} />
          </JobProvider>
        </ToastProvider>
      </BrowserRouter>
    </MetaCtx.Provider>
  );
}

function Layout({ meta }: { meta: Meta }) {
  const [nav, setNav] = useState(false);
  const [cmd, setCmd] = useState(false);
  const loc = useLocation();
  return (
    <div className="min-h-full">
      <Sidebar open={nav} onClose={() => setNav(false)} />
      <div className="lg:pl-60">
        <Topbar onMenu={() => setNav(true)} onSearch={() => setCmd(true)} />
        {meta.demo && (
          <div className="border-b border-med/20 bg-med/10 px-4 py-1.5 text-center text-[12px] text-med">
            <Sparkles size={12} className="mr-1.5 inline -mt-0.5" /><span className="font-medium">Demo workspace:</span> competitor moves shown here are illustrative samples, not real observations.
            <span className="hidden sm:inline"> Run without <code className="font-mono">SENTINEL_DEMO</code> for live data.</span>
          </div>
        )}
        <main className="mx-auto max-w-[1400px] px-4 py-7 sm:px-6 lg:px-8">
          <AnimatePresence mode="wait">
            <motion.div key={loc.pathname} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
              <Routes location={loc}>
                <Route path="/" element={<Overview />} />
                <Route path="/signals" element={<Signals />} />
                <Route path="/competitors" element={<CompetitorList />} />
                <Route path="/competitors/:id" element={<CompetitorDetailPage />} />
                <Route path="/content" element={<Content />} />
                <Route path="/ai" element={<AiVisibility />} />
                <Route path="/digest" element={<Digest />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<Overview />} />
              </Routes>
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      <CommandPalette open={cmd} setOpen={setCmd} />
    </div>
  );
}

function Boot({ error }: { error: Error | null }) {
  return (
    <div className="grid min-h-full place-items-center p-8">
      {error ? (
        <div className="card max-w-sm p-6 text-center">
          <div className="text-[15px] font-medium text-ink">Can't reach the Sentinel API</div>
          <p className="mt-1 text-[13px] text-ink-3">Start it with <code className="font-mono">sentinel serve</code>, then reload.</p>
        </div>
      ) : (
        <div className="w-64 space-y-3"><Skeleton className="h-6 w-1/2" /><Skeleton className="h-4" /><Skeleton className="h-4 w-3/4" /></div>
      )}
    </div>
  );
}

function Login() {
  const [v, setV] = useState("");
  return (
    <div className="glow grid min-h-full place-items-center p-6">
      <form onSubmit={(e) => { e.preventDefault(); setToken(v); }} className="card w-full max-w-sm p-7">
        <div className="mb-5 grid size-10 place-items-center rounded-xl bg-accent-soft text-accent-ink"><KeyRound size={18} /></div>
        <h1 className="text-[18px] font-semibold text-ink">Sign in to Sentinel</h1>
        <p className="mt-1 text-[13px] text-ink-3">Enter the access token set in <code className="font-mono">SENTINEL_TOKEN</code>.</p>
        <input type="password" autoFocus value={v} onChange={(e) => setV(e.target.value)} placeholder="Access token"
          className="mt-5 h-10 w-full rounded-lg bg-sunken px-3 text-[14px] text-ink outline-none ring-1 ring-inset ring-line focus:ring-accent/50" />
        <Button variant="primary" className="mt-3 w-full" type="submit">Continue</Button>
      </form>
    </div>
  );
}
