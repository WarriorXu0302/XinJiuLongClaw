import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Form, Input, message, Typography } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useAuthStore } from '../stores/authStore';
import api from '../api/client';

const { Title } = Typography;

interface LoginForm {
  username: string;
  password: string;
}

function Login() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: LoginForm) => {
    setLoading(true);
    try {
      const { data } = await api.post('/auth/login', values);
      // Decode username/roles from token payload
      const payload = JSON.parse(atob(data.access_token.split('.')[1]));
      login(data.access_token, data.refresh_token, payload.username, payload.roles || [], payload.brand_ids || []);
      message.success('登录成功');
      // 手机端自动跳打卡页
      const isMobile = /Mobi|Android|iPhone/i.test(navigator.userAgent);
      const isSalesman = (payload.roles || []).includes('salesman');
      navigate(isMobile && isSalesman ? '/m/checkin' : '/dashboard');
    } catch (err: any) {
      message.error(err?.response?.data?.detail ?? '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      background: '#f0f2f5',
    }}>
      <Card style={{ width: 380, boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={3} style={{ margin: 0 }}>新鑫久隆 ERP</Title>
          <p style={{ color: '#999', marginTop: 8 }}>请登录您的账号</p>
        </div>
        <Form<LoginForm> onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}

export default Login;
