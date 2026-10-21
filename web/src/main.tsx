import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { captureTokenFromUrl } from "./lib/api";

captureTokenFromUrl();  // before the first request, so a kiosk opened with ?token= is signed in

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
