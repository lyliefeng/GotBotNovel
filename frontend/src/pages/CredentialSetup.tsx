import { useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Input, Result, Spin, Typography, message, theme } from 'antd';
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { authApi } from '../services/api';

interface CredentialValues {
  username: string;
  password: string;
  confirmPassword: string;
}

export default function CredentialSetup() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [checking, setChecking] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [form] = Form.useForm<CredentialValues>();
  const { token } = theme.useToken();

  const redirect = searchParams.get('redirect') || '/';

  useEffect(() => {
    const checkUser = async () => {
      try {
        const user = await authApi.getCurrentUser();
        if (!user.requires_credentials_update) {
          navigate(redirect, { replace: true });
          return;
        }
        form.setFieldValue('username', '');
      } catch {
        navigate(`/login?redirect=${encodeURIComponent(redirect)}`, { replace: true });
      } finally {
        setChecking(false);
      }
    };
    checkUser();
  }, [form, navigate, redirect]);

  const handleSubmit = async (values: CredentialValues) => {
    setSubmitting(true);
    setError('');
    try {
      await authApi.updateCredentials(values.username.trim(), values.password);
      message.success('账号和密码设置成功，请使用新凭据登录');
      await authApi.logout();
      navigate(`/login?redirect=${encodeURIComponent(redirect)}`, { replace: true });
    } catch (err: unknown) {
      const apiError = err as { response?: { data?: { detail?: string } } };
      setError(apiError.response?.data?.detail || '账号和密码设置失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  if (checking) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <Spin size="large" tip="正在检查首次登录状态..." />
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: 24,
        background: `linear-gradient(135deg, ${token.colorBgLayout}, ${token.colorPrimaryBg})`,
      }}
    >
      <Card style={{ width: '100%', maxWidth: 520, borderRadius: 18 }}>
        <Result
          icon={<SafetyCertificateOutlined style={{ color: token.colorPrimary }} />}
          title="请设置自己的账号和密码"
          subTitle="当前使用的是系统随机生成的临时凭据。完成设置前不能进入系统，设置成功后需要使用新凭据重新登录。"
          style={{ padding: '8px 0 20px' }}
        />

        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 18 }} /> : null}

        <Form form={form} layout="vertical" size="large" onFinish={handleSubmit}>
          <Form.Item
            name="username"
            label="新账号"
            rules={[
              { required: true, message: '请输入新账号' },
              { min: 3, max: 64, message: '账号长度必须为 3-64 个字符' },
              { pattern: /^\S+$/, message: '账号不能包含空格' },
            ]}
          >
            <Input prefix={<UserOutlined />} placeholder="设置便于记忆的登录账号" autoComplete="username" />
          </Form.Item>

          <Form.Item
            name="password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '密码长度至少为 6 个字符' },
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="设置自己的登录密码" autoComplete="new-password" />
          </Form.Item>

          <Form.Item
            name="confirmPassword"
            label="确认新密码"
            dependencies={['password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) return Promise.resolve();
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="再次输入新密码" autoComplete="new-password" />
          </Form.Item>

          <Button type="primary" htmlType="submit" block loading={submitting} style={{ height: 46 }}>
            保存账号和密码
          </Button>
        </Form>

        <Typography.Paragraph type="secondary" style={{ margin: '16px 0 0', textAlign: 'center', fontSize: 12 }}>
          临时凭据仅用于首次登录，设置完成后会自动失效。
        </Typography.Paragraph>
      </Card>
    </div>
  );
}
