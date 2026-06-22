import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./design-system.css";

const savedTheme = globalThis.localStorage?.getItem("adv-search-flights-theme");
const initialTheme = savedTheme === "light" || savedTheme === "dark" ? savedTheme : "dark";
document.documentElement.dataset.theme = initialTheme;
document.documentElement.style.colorScheme = initialTheme;

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
