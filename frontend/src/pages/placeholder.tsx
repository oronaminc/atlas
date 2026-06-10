import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/common/empty-state";

export function PlaceholderPage({ title }: { title: string }) {
  return (
    <div>
      <PageHeader title={title} />
      <EmptyState title="구현 예정" description="이 화면은 곧 구현됩니다." />
    </div>
  );
}
