import { useAsyncData } from '../hooks/useAsyncData';
import { useI18n } from '../hooks/useI18n';
import { catalogApi } from '../services/api/catalogApi';
import { EmptyRow, ErrorRow, LoadingRow, PageShell, Panel } from '../components/ui/PageShell';

export default function Skills() {
  const { t } = useI18n();
  const { data, loading, error, reload } = useAsyncData(() => catalogApi.listSkills(), []);
  const skills = data ?? [];

  return (
    <PageShell
      eyebrow={t('pages.skills.eyebrow')}
      title={t('pages.skills.title')}
      description={t('pages.skills.description')}
      actions={
        <button
          type="button"
          onClick={reload}
          className="bg-surface-container hover:bg-surface-container-high text-on-surface-variant font-label-mono-xs text-label-mono-xs px-space-sm py-1.5 rounded transition-colors flex items-center gap-1"
        >
          <span className="material-symbols-outlined text-[14px]">refresh</span>
          {t('common.reload')}
        </button>
      }
    >
      {loading ? (
        <LoadingRow label={t('pages.skills.loading')} />
      ) : error ? (
        <ErrorRow message={error} onRetry={reload} />
      ) : skills.length === 0 ? (
        <EmptyRow message={t('pages.skills.empty')} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-space-md">
          {skills.map((skill) => (
            <Panel key={skill.name} className="flex flex-col gap-space-sm">
              <div className="flex items-start justify-between gap-space-sm">
                <div className="flex items-center gap-space-xs min-w-0">
                  <span className="material-symbols-outlined text-[18px] text-primary">
                    psychology
                  </span>
                  <span className="font-body-sm text-body-sm font-medium text-on-surface truncate">
                    {skill.name}
                  </span>
                </div>
                <span
                  className={`font-label-mono-xs text-label-mono-xs bg-surface-container px-1.5 py-0.5 rounded shrink-0 ${
                    skill.enabled ? 'text-tertiary' : 'text-outline'
                  }`}
                >
                  {t(skill.enabled ? 'pages.skills.enabled' : 'pages.skills.disabled')}
                </span>
              </div>
              {/* The description is the backend's own text for the skill: data, not copy. */}
              <p className="font-body-sm text-body-sm text-on-surface-variant">{skill.description}</p>
              <div className="flex items-center justify-between font-label-mono-xs text-label-mono-xs text-outline">
                <span>v{skill.version}</span>
                <span>{t('pages.skills.toolsCount', { count: skill.tools.length })}</span>
              </div>
              {skill.tools.length > 0 && (
                <div className="flex flex-wrap gap-space-xs pt-space-xs border-t border-outline-variant/20">
                  {skill.tools.map((tool) => (
                    <span
                      key={tool}
                      className="font-label-mono-xs text-label-mono-xs bg-surface-container-lowest text-on-surface-variant px-1.5 py-0.5 rounded"
                    >
                      {tool}
                    </span>
                  ))}
                </div>
              )}
            </Panel>
          ))}
        </div>
      )}
    </PageShell>
  );
}
