import { FormEvent, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type InviteInfo = {
  email: string | null
  phone: string | null
  role: 'admin' | 'non-admin'
  expires_at: string
}

export default function InvitationSetup() {
  useDocumentTitle('CRM - Set Up Account')
  const { token } = useParams()
  const navigate = useNavigate()
  const setAuth = useAuthStore((state) => state.setAuth)
  const [invite, setInvite] = useState<InviteInfo | null>(null)
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    const load = async () => {
      if (!token) return
      const response = await fetch(`${API_BASE_URL}/api/invites/${token}`)
      const data = await response.json()
      if (!response.ok) {
        setError(data.detail ?? 'Invalid invite')
        return
      }
      setInvite(data)
      setEmail(data.email ?? '')
      setPhone(data.phone ?? '')
    }
    load()
  }, [token])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    const response = await fetch(`${API_BASE_URL}/api/invites/${token}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        first_name: firstName || null,
        last_name: lastName || null,
        email: email || null,
        phone: phone || null,
        password,
        password_confirmation: confirmation,
      }),
    })
    const data = await response.json()
    if (!response.ok) return setError(data.detail ?? 'Failed to complete invitation')
    localStorage.setItem('crmssi:users-updated', String(Date.now()))
    setAuth(data.access_token)
    setSuccess('Account created successfully. Redirecting...')
    setTimeout(() => navigate('/', { replace: true }), 1200)
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-6">
      <form className="w-full max-w-lg animate-scale-in space-y-3 rounded-3xl border border-gray-200 bg-white p-5 shadow-sm" onSubmit={submit}>
        <h1 className="text-2xl font-semibold">Set up account</h1>
        {invite ? <p className="text-sm text-gray-500">Role: {invite.role}</p> : null}
        <div className="grid gap-3 md:grid-cols-2">
          <Input label="First name" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
          <Input label="Last name" value={lastName} onChange={(e) => setLastName(e.target.value)} />
        </div>
        <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <Input label="Phone" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <Input label="Confirm password" type="password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} required />
        {error ? <p className="text-sm text-rose-500">{error}</p> : null}
        {success ? <p className="text-sm text-emerald-600">{success}</p> : null}
        <Button type="submit" className="w-full">Set up account</Button>
      </form>
    </main>
  )
}
