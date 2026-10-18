import { useState } from 'react';
import type { PermissionRequest } from '../../types';
import { permissionsApi } from '../../services/api/permissionsApi';

interface PermissionDialogProps {
  request: PermissionRequest;
  runId: string;
  onApproved?: () => void;
  onRejected?: () => void;
  onClose?: () => void;
}

function riskTone(risk: string): string {
  if (risk === 'HIGH') return 'bg-error-container/30 text-error border-error/40';
  if (risk === 'MEDIUM') return 'bg-primary/10 text-primary border-primary/30';
  return 'bg-tertiary/10 text-tertiary border-tertiary/30';
}

export function PermissionDialog({ request, runId, onApproved, onRejected, onClose }: PermissionDialogProps) {
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleApprove = async () => {
    setIsProcessing(true);
    setError(null);
    try {
      await permissionsApi.approveRequest(runId, request.id);
      onApproved?.();
      onClose?.();
    } catch (err) {
      setError('No se pudo aprobar la solicitud');
      console.error(err);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleReject = async () => {
    setIsProcessing(true);
    setError(null);
    try {
      await permissionsApi.rejectRequest(runId, request.id);
      onRejected?.();
      onClose?.();
    } catch (err) {
      setError('No se pudo rechazar la solicitud');
      console.error(err);
    } finally {
      setIsProcessing(false);
    }
  };

  const isDisabled = request.status !== 'PENDING' || isProcessing;

  return (
    <div className="fixed inset-0 bg-[rgba(11,13,18,0.85)] backdrop-blur flex items-center justify-center p-space-md z-50">
      <div className="bg-surface-container-high border border-outline-variant/40 rounded-lg shadow-overlay max-w-md w-full">
        <div className="p-space-lg flex flex-col gap-space-md">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-space-sm">
              <div className="w-8 h-8 rounded bg-error-container/40 flex items-center justify-center text-error">
                <span className="material-symbols-outlined text-[18px]">shield_lock</span>
              </div>
              <h2 className="font-headline-sm text-headline-sm font-semibold text-on-surface">
                NEXUS necesita tu permiso
              </h2>
            </div>
            <button
              onClick={onClose}
              className="text-outline hover:text-on-surface transition-colors"
              disabled={isProcessing}
            >
              <span className="material-symbols-outlined text-[18px]">close</span>
            </button>
          </div>

          <div className="flex flex-col gap-space-sm">
            <div className="bg-surface-container-lowest rounded p-space-sm flex flex-col gap-0.5">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Acción</span>
              <span className="font-code-base text-code-base text-secondary">{request.tool_name}</span>
            </div>

            <div className="flex items-center justify-between bg-surface-container-lowest rounded p-space-sm">
              <div className="flex flex-col gap-0.5">
                <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Skill</span>
                <span className="font-body-sm text-body-sm text-on-surface">{request.skill_name}</span>
              </div>
              <div className="flex flex-col items-end gap-0.5">
                <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Riesgo</span>
                <span className={`font-label-mono-xs text-label-mono-xs border px-2 py-0.5 rounded ${riskTone(request.risk_level)}`}>
                  {request.risk_level}
                </span>
              </div>
            </div>

            <div className="bg-surface-container-lowest rounded p-space-sm flex flex-col gap-0.5">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Motivo</span>
              <span className="font-body-sm text-body-sm text-on-surface-variant">{request.reason}</span>
            </div>

            {error && (
              <div className="bg-error-container/30 border border-error/40 text-error px-space-sm py-1.5 rounded font-body-sm text-body-sm">
                {error}
              </div>
            )}
          </div>

          <div className="flex gap-space-sm pt-space-xs">
            <button
              onClick={handleReject}
              disabled={isDisabled}
              className="flex-1 px-space-md py-1.5 bg-surface-container hover:bg-surface-container-high border border-outline-variant/40 text-error rounded font-body-sm text-body-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Rechazar
            </button>
            <button
              onClick={handleApprove}
              disabled={isDisabled}
              className="flex-1 px-space-md py-1.5 bg-primary text-on-primary hover:bg-primary-container rounded font-body-sm text-body-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isProcessing ? 'Procesando…' : 'Aprobar'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
