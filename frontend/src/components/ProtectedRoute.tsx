import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Spin } from 'antd';
import { authApi } from '../services/api';
import { sessionManager } from '../utils/sessionManager';

interface ProtectedRouteProps {
  children: ReactNode;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
  const [requiresCredentialsUpdate, setRequiresCredentialsUpdate] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const user = await authApi.getCurrentUser();
        setRequiresCredentialsUpdate(Boolean(user.requires_credentials_update));
        setIsAuthenticated(true);
        // 启动会话管理器
        sessionManager.start();
      } catch {
        setIsAuthenticated(false);
        // 停止会话管理器
        sessionManager.stop();
      }
    };
    checkAuth();
    
    return () => {
      // 组件卸载时不停止会话管理器，让它在整个应用生命周期内运行
    };
  }, []);

  if (isAuthenticated === null) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
      }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to={`/login?redirect=${encodeURIComponent(location.pathname)}`} replace />;
  }

  if (requiresCredentialsUpdate) {
    return <Navigate to={`/auth/setup?redirect=${encodeURIComponent(location.pathname)}`} replace />;
  }

  return <>{children}</>;
}