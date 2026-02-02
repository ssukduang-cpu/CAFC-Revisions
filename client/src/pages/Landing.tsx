import { Button } from "@/components/ui/button";
import { Scale, Shield, BookOpen, ArrowRight } from "lucide-react";

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

          <Button size="lg" asChild className="mb-16" data-testid="get-started-button">
            <a href="/api/login">
              Get Started
              <ArrowRight className="h-5 w-5 ml-2" />
            </a>
          </Button>

          <div className="grid md:grid-cols-3 gap-8 text-left">
            <div className="p-6 bg-white dark:bg-slate-800 rounded-xl shadow-sm border">
              <div className="p-3 bg-primary/10 rounded-lg w-fit mb-4">
                <Scale className="h-6 w-6 text-primary" />
              </div>
              <h3 className="font-semibold text-lg mb-2">Citation-Grounded</h3>
              <p className="text-muted-foreground">
                Every answer includes verbatim quotes and proper citations from CAFC opinions. 93.9% verification accuracy.
              </p>
            </div>

            <div className="p-6 bg-white dark:bg-slate-800 rounded-xl shadow-sm border">
              <div className="p-3 bg-primary/10 rounded-lg w-fit mb-4">
                <Shield className="h-6 w-6 text-primary" />
              </div>
              <h3 className="font-semibold text-lg mb-2">Attorney Mode</h3>
              <p className="text-muted-foreground">
                Strict provenance verification flags unverified statements. Built for litigation-grade research.
              </p>
            </div>

            <div className="p-6 bg-white dark:bg-slate-800 rounded-xl shadow-sm border">
              <div className="p-3 bg-primary/10 rounded-lg w-fit mb-4">
                <BookOpen className="h-6 w-6 text-primary" />
              </div>
              <h3 className="font-semibold text-lg mb-2">Precedential Opinions</h3>
              <p className="text-muted-foreground">
                Access the full corpus of CAFC precedential opinions plus landmark SCOTUS patent cases.
              </p>
            </div>
          </div>
        </main>

        <footer className="text-center text-sm text-muted-foreground mt-16 pb-8">
          <p>This is an AI-assisted research tool, not legal advice.</p>
          <p className="mt-1">© 2025 CAFC Opinion Assistant</p>
        </footer>
      </div>
    </div>
  );
}
