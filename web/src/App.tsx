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
import { DeepDive, DeepDives } from "./pages/DeepDive";
import Messaging from "./pages/Messaging";
import { HiringPage, InfrastructurePage, MoneyPage, PositioningPage, ProductPage, RadarPage, StackPage } from "./pages/Modules";
import Coverage from "./pages/Coverage";
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
          <div className="mx-4 rounded-full bg-elev px-4 py-2 text-center text-[12px] text-ink-2 ring-1 ring-line sm:mx-8">
            <Sparkles size={12} className="mr-1.5 inline -mt-0.5 text-med" />Demo workspace, competitor moves shown here are illustrative samples, not real observations.
            <span className="hidden sm:inline"> Run without <code className="font-mono">SENTINEL_DEMO</code> for live data.</span>
          </div>
        )}
        <main className="mx-auto max-w-[1360px] px-4 pb-16 pt-8 sm:px-8 lg:px-10">
          <AnimatePresence mode="wait">
            <motion.div key={loc.pathname} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
              <Routes location={loc}>
                <Route path="/" element={<Overview />} />
                <Route path="/signals" element={<Signals />} />
                <Route path="/competitors" element={<CompetitorList />} />
                <Route path="/competitors/:id" element={<CompetitorDetailPage />} />
                <Route path="/deep-dives" element={<DeepDives />} />
                <Route path="/deep-dives/:id" element={<DeepDive />} />
                <Route path="/stack" element={<StackPage />} />
                <Route path="/infrastructure" element={<InfrastructurePage />} />
                <Route path="/radar" element={<RadarPage />} />
                <Route path="/product" element={<ProductPage />} />
                <Route path="/messaging" element={<Messaging />} />
                <Route path="/social" element={<Messaging />} />
                <Route path="/hiring" element={<HiringPage />} />
                <Route path="/money" element={<MoneyPage />} />
                <Route path="/positioning" element={<PositioningPage />} />
                <Route path="/content" element={<Messaging />} />
                <Route path="/coverage" element={<Coverage />} />
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
          <div className="text-[15px] text-ink">Can't reach the Sentinel API</div>
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
    <div className="dotgrid grid min-h-full place-items-center p-6">
      <form onSubmit={(e) => { e.preventDefault(); setToken(v); }} className="card w-full max-w-sm p-7">
        <div className="mb-5 grid size-10 place-items-center rounded-full bg-sunken text-ink-2"><KeyRound size={16} /></div>
        <h1 className="text-[20px] tracking-[-0.02em] text-ink">Sign in to Sentinel</h1>
        <p className="mt-1 text-[13px] text-ink-3">Enter the access token set in <code className="font-mono">SENTINEL_TOKEN</code>.</p>
        <input type="password" autoFocus value={v} onChange={(e) => setV(e.target.value)} placeholder="Access token"
          className="mt-5 h-11 w-full rounded-full bg-sunken px-4 text-[14px] text-ink outline-none" />
        <Button variant="primary" className="mt-3 w-full" type="submit">Continue</Button>
      </form>
    </div>
  );
}
