import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Input from '../Input'
import Select from '../Select'
import Textarea from '../Textarea'
import Badge from '../Badge'

describe('Input', () => {
  it('associates the label with the field and reflects typing', () => {
    const onChange = vi.fn()
    render(<Input label="Email" value="" onChange={onChange} placeholder="you@co" />)
    const field = screen.getByLabelText('Email')
    expect(field).toHaveAttribute('placeholder', 'you@co')
    fireEvent.change(field, { target: { value: 'a@b.co' } })
    expect(onChange).toHaveBeenCalled()
  })

  it('marks the field invalid and shows the error text', () => {
    render(<Input label="Name" error="Required" readOnly value="" />)
    const field = screen.getByLabelText('Name')
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('Required')).toBeInTheDocument()
  })
})

describe('Select', () => {
  it('renders options and fires change', () => {
    const onChange = vi.fn()
    render(
      <Select label="Mode" value="a" onChange={onChange}>
        <option value="a">A</option>
        <option value="b">B</option>
      </Select>,
    )
    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'b' } })
    expect(onChange).toHaveBeenCalled()
  })
})

describe('Textarea', () => {
  it('renders with a label', () => {
    render(<Textarea label="Notes" readOnly value="hello" />)
    expect(screen.getByLabelText('Notes')).toHaveValue('hello')
  })
})

describe('Badge', () => {
  it('renders content with tone styling', () => {
    render(<Badge tone="emerald">Active</Badge>)
    const badge = screen.getByText('Active')
    expect(badge.className).toContain('bg-emerald-100')
  })
})
