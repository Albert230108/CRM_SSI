import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import MultiSelect, { type MultiSelectOption } from '../MultiSelect'

const OPTIONS: MultiSelectOption<string>[] = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' },
  { value: 'c', label: 'Gamma' },
]

describe('MultiSelect', () => {
  it('opens the popover and toggles a value on without closing (multi-select)', () => {
    const onChange = vi.fn()
    render(<MultiSelect label="Due" options={OPTIONS} selected={[]} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: /Due/ }))
    fireEvent.click(screen.getByText('Beta'))

    expect(onChange).toHaveBeenCalledWith(['b'])
    // Popover stays open in multi-select mode.
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('deselects an already-selected value', () => {
    const onChange = vi.fn()
    render(<MultiSelect label="Due" options={OPTIONS} selected={['a', 'b']} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: /Due/ }))
    fireEvent.click(screen.getByText('Alpha'))

    expect(onChange).toHaveBeenCalledWith(['b'])
  })

  it('shows a count badge for the current selection size', () => {
    render(<MultiSelect label="Due" options={OPTIONS} selected={['a', 'c']} onChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Due/ })).toHaveTextContent('2')
  })

  it('replaces the selection and closes in single-select mode', () => {
    const onChange = vi.fn()
    render(
      <MultiSelect
        label="Status"
        singleSelect
        options={OPTIONS}
        selected={['a']}
        onChange={onChange}
        summary={(sel) => `Status: ${sel[0] ?? 'None'}`}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Status/ }))
    fireEvent.click(screen.getByText('Gamma'))

    expect(onChange).toHaveBeenCalledWith(['c'])
    // Single-select closes the popover after choosing.
    expect(screen.queryByText('Alpha')).not.toBeInTheDocument()
  })

  it('Select all / Clear all cover every option', () => {
    const onChange = vi.fn()
    render(<MultiSelect label="Due" options={OPTIONS} selected={['a']} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: /Due/ }))
    fireEvent.click(screen.getByText('Select all'))
    expect(onChange).toHaveBeenCalledWith(['a', 'b', 'c'])

    fireEvent.click(screen.getByText('Clear all'))
    expect(onChange).toHaveBeenCalledWith([])
  })
})
