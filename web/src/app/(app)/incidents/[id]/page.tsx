import { CaseDetailScreen } from '@/components/cases/case-detail-screen'

export default async function IncidentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  return <CaseDetailScreen caseId={id} />
}
