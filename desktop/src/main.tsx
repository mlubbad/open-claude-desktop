import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { applyUiPrefs } from "./state/uiPrefs";
import "./styles.css";

applyUiPrefs(); // chat font + motion, before first paint

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
