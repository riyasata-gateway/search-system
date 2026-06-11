import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import Login from "./pages/Login";
import PharmacistDashboard from "./pages/PharmacistDashboard";
import BrandPulse from "./pages/BrandPulse";
import BrandSetup from "./pages/BrandSetup";
import Alerts from "./pages/Alerts";
import AdverseEventReview from "./pages/AdverseEventReview";
import Admin from "./pages/Admin";
import Search from "./pages/Search";
import BrandPotential from "./pages/BrandPotential";
import Analytics from "./pages/Analytics";
import Layout from "./components/Layout";

function ProtectedRoute({ children, roles }: { children: React.ReactNode; roles?: string[] }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  const { user } = useAuth();

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route
            index
            element={
              user?.role === "pharmacist" ? (
                <Navigate to="/pharmacist" replace />
              ) : user?.role === "marketing" || user?.role === "brand_manager" ? (
                <Navigate to="/brand-pulse" replace />
              ) : (
                <Navigate to="/admin" replace />
              )
            }
          />
          <Route
            path="pharmacist"
            element={
              <ProtectedRoute roles={["pharmacist", "admin"]}>
                <PharmacistDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="brand-pulse"
            element={
              <ProtectedRoute roles={["marketing", "brand_manager", "admin"]}>
                <BrandPulse />
              </ProtectedRoute>
            }
          />
          <Route
            path="setup"
            element={
              <ProtectedRoute roles={["marketing", "brand_manager", "admin"]}>
                <BrandSetup />
              </ProtectedRoute>
            }
          />
          <Route
            path="alerts"
            element={
              <ProtectedRoute>
                <Alerts />
              </ProtectedRoute>
            }
          />
          <Route
            path="adverse-events"
            element={
              <ProtectedRoute roles={["pharmacist", "admin"]}>
                <AdverseEventReview />
              </ProtectedRoute>
            }
          />
          <Route
            path="search"
            element={
              <ProtectedRoute>
                <Search />
              </ProtectedRoute>
            }
          />
          <Route
            path="brand-potential"
            element={
              <ProtectedRoute roles={["marketing", "brand_manager", "admin"]}>
                <BrandPotential />
              </ProtectedRoute>
            }
          />
          <Route
            path="analytics"
            element={
              <ProtectedRoute>
                <Analytics />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin"
            element={
              <ProtectedRoute roles={["admin"]}>
                <Admin />
              </ProtectedRoute>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
