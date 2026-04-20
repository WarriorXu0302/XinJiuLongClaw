import { Navigate } from 'react-router-dom';
import { Result, Button } from 'antd';
import { useAuthStore } from '../stores/authStore';
import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** 若指定角色，则只有匹配其一的用户可访问。admin 总是通过。 */
  requiredRoles?: string[];
}

function AuthGuard({ children, requiredRoles }: Props) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const roles = useAuthStore((s) => s.roles);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (requiredRoles?.length && !roles.includes('admin')) {
    const allowed = requiredRoles.some(r => roles.includes(r));
    if (!allowed) {
      return (
        <Result
          status="403"
          title="无权访问"
          subTitle={`该页面需要以下角色之一：${requiredRoles.join(' / ')}`}
          extra={<Button type="primary" onClick={() => window.history.back()}>返回</Button>}
        />
      );
    }
  }

  return <>{children}</>;
}

export default AuthGuard;
