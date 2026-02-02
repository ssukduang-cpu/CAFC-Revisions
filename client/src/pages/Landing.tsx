import { Button } from "@/components/ui/button";
import { Scale, ArrowRight } from "lucide-react";

export default function Landing() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
      <div className="container mx-auto px-4 py-8">
        <nav className="flex items-center justify-between mb-16">
          <div className="flex items-center gap-2">
            <Scale className="h-8 w-8 text-primary" />
            <span className="text-xl font-bold">CAFC Opinion Assistant</span>
          </div>
          <Button asChild data-testid="login-button">
            <a href="/api/login">
              Sign In
              <ArrowRight className="h-4 w-4 ml-2" />
            </a>
          </Button>
        </nav>

        <main className="max-w-4xl mx-auto text-center py-20">
          <h1 className="text-5xl font-serif font-bold tracking-tight text-foreground mb-6">
            Federal Circuit Legal Research
            <br />
            <span className="text-primary">Powered by AI</span>
          </h1>
          
          <p className="text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
            Natural-language conversations with precedential opinions from the Court of Appeals for the Federal Circuit. Citation-backed answers directly from opinion text.
          </p>

          <Button size="lg" asChild data-testid="get-started-button">
            <a href="/api/login">
              Get Started
              <ArrowRight className="h-5 w-5 ml-2" />
            </a>
          </Button>
        </main>

        <footer className="text-center text-sm text-muted-foreground mt-16 pb-8">
          <p>This is an AI-assisted research tool, not legal advice.</p>
          <p className="mt-1">© 2025 CAFC Opinion Assistant</p>
        </footer>
      </div>
    </div>
  );
}
