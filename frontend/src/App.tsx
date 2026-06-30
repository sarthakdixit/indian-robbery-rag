import { ErrorBoundary } from "react-error-boundary";
import { Routes, Route } from "react-router-dom";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { AppErrorFallback } from "@/components/layout/ErrorBoundary";
import { FirstVisitModal } from "@/components/disclaimer/FirstVisitModal";
import { HomePage } from "@/pages/HomePage";
import { AdminPage } from "@/pages/AdminPage";
import { TermsPage } from "@/pages/TermsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function App() {
  return (
    <ErrorBoundary FallbackComponent={AppErrorFallback}>
      <FirstVisitModal />
      <div className="flex min-h-screen flex-col">
        <Header />
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
        <Footer />
      </div>
    </ErrorBoundary>
  );
}
