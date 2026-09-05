import { Routes, Route } from "react-router-dom";
import ConfigPage from "./pages/ConfigPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ConfigPage />} />
      <Route path="/runs/:runId" element={<DashboardPage />} />
    </Routes>
  );
}
