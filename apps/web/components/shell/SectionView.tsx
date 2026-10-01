import { Construction } from "lucide-react";
import CopyrightFooter from "./CopyrightFooter";
import AppShell from "./AppShell";
import { EmptyState } from "../layout/empty-state";
import { PageHeader } from "../layout/page-header";
import { Workspace, WorkspaceBody } from "../layout/workspace";
import { Button } from "../ui/button";
import TransitionLink from "./TransitionLink";

export default function SectionView({ name, description }: { name: string; description: string }) {
  const title = name.charAt(0).toUpperCase() + name.slice(1);
  return <AppShell title={title} footer={<CopyrightFooter />}><Workspace><PageHeader title={title} description={description} /><WorkspaceBody><EmptyState icon={<Construction />} title="Not available yet" description="This section is planned but has not been built." actions={<Button variant="outline" asChild><TransitionLink href="/library">Explore your library</TransitionLink></Button>} /></WorkspaceBody></Workspace></AppShell>;
}
