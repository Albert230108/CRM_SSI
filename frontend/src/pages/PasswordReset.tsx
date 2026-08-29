import { FormEvent, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export default function PasswordReset() {
  useDocumentTitle('CRM - Reset Password')
  const { token } = useParams()
  const navigate = useNavigate()
  const setAuth = useAuthStore((state) => state.setAuth)
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const response = await fetch(`${API_BASE_URL}/api/auth/password-reset/${token}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, password_confirmation: confirmation }),
    })
    const data = await response.json()
    if (!response.ok) return setError(data.detail ?? 'Failed to reset password')
    setAuth(data.access_token)
    navigate('/', { replace: true })
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-6">
      <form className="w-full max-w-md animate-scale-in space-y-3 rounded-3xl border border-gray-200 bg-white p-5 shadow-sm" onSubmit={submit}>
        <h1 className="text-2xl font-semibold text-gray-900">Reset password</h1>
        <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <Input label="Confirm password" type="password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} required />
        {error ? <p className="text-sm text-rose-500">{error}</p> : null}
        <Button type="submit" className="w-full">Set new password</Button>
      </form>
    </main>
  )
}
