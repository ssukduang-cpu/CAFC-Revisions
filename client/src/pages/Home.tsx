import { MainLayout } from "@/components/layout/MainLayout";
import { OpinionLibrary } from "@/components/OpinionLibrary";
import { ChatInterface } from "@/components/ChatInterface";
import { SourcesPanel } from "@/components/SourcesPanel";

export default function Home() {
  return (
    <MainLayout
      sidebar={<OpinionLibrary />}
      chat={<ChatInterface />}
      sources={<SourcesPanel />}
    />
  );
}
