import { Switch, Route } from "wouter";
import { queryClient } from "./lib/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppProvider } from "@/context/AppContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { AuthGuard } from "@/components/AuthGuard";
import Home from "@/pages/Home";
import Admin from "@/pages/Admin";
import UserAdmin from "@/pages/UserAdmin";
import CitationGuide from "@/pages/CitationGuide";
import TelemetryDashboard from "@/pages/TelemetryDashboard";
import EvalDashboard from "@/pages/EvalDashboard";
import NotFound from "@/pages/not-found";

function Router() {
  return (
    <Switch>
      <Route path="/" component={Home} />
      <Route path="/admin" component={Admin} />
      <Route path="/users" component={UserAdmin} />
      <Route path="/citation-guide" component={CitationGuide} />
      <Route path="/telemetry" component={TelemetryDashboard} />
      <Route path="/eval" component={EvalDashboard} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AppProvider>
          <TooltipProvider>
            <Toaster />
            <AuthGuard>
              <Router />
            </AuthGuard>
          </TooltipProvider>
        </AppProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
