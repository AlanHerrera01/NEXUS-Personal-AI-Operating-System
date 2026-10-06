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
      setError('Failed to approve request');
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
      setError('Failed to reject request');
      console.error(err);
    } finally {
      setIsProcessing(false);
    }
  };

  const isDisabled = request.status !== 'PENDING' || isProcessing;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-gray-900">NEXUS needs your permission</h2>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600"
              disabled={isProcessing}
            >
              ✕
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium text-gray-700">Action</label>
              <p className="text-lg font-semibold text-gray-900">{request.tool_name}</p>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">Tool</label>
              <p className="text-gray-600">{request.skill_name}</p>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">Risk Level</label>
              <span className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium ${
                request.risk_level === 'HIGH'
                  ? 'bg-red-100 text-red-800'
                  : request.risk_level === 'MEDIUM'
                  ? 'bg-yellow-100 text-yellow-800'
                  : 'bg-green-100 text-green-800'
              }`}>
                {request.risk_level}
              </span>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">Reason</label>
              <p className="text-gray-600">{request.reason}</p>
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded">
                {error}
              </div>
            )}
          </div>

          <div className="flex gap-3 mt-6">
            <button
              onClick={handleReject}
              disabled={isDisabled}
              className="flex-1 px-4 py-2 border border-gray-300 rounded text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Reject
            </button>
            <button
              onClick={handleApprove}
              disabled={isDisabled}
              className="flex-1 px-4 py-2 bg-nexus-600 text-white rounded hover:bg-nexus-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isProcessing ? 'Processing...' : 'Approve'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
