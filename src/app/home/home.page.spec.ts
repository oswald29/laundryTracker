import type { ComponentFixture } from '@angular/core/testing';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import type { LaundryOrder } from '../services/laundry.service';

import { HomePage } from './home.page';

describe('HomePage', () => {
  let component: HomePage;
  let fixture: ComponentFixture<HomePage>;

  beforeEach(async () => {
    fixture = TestBed.createComponent(HomePage);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('strips non-numeric characters from phone input and shows a notice', () => {
    component.onPhoneInput(
      new CustomEvent<{ value?: string | null }>('ionInput', { detail: { value: '0917abc1234' } }),
    );

    expect(component.draft.phone).toBe('09171234');
    expect(component.phoneInputError()).toBe('Phone number can contain numbers only.');
  });

  it('clears the phone notice after numeric input', () => {
    component.onPhoneInput(new CustomEvent<{ value?: string | null }>('ionInput', { detail: { value: '0917abc' } }));
    component.onPhoneInput(new CustomEvent<{ value?: string | null }>('ionInput', { detail: { value: '09171234' } }));

    expect(component.phoneInputError()).toBe('');
  });

  it('shows new received orders in the In Progress filter without a Washing label', () => {
    const newOrder: LaundryOrder = {
      id: 1,
      customerName: 'Alex Santos',
      phone: '',
      serviceType: 'Wash & Fold',
      weightKg: 1,
      price: 45,
      dueDate: '',
      status: 'Received',
      createdAt: '',
      updatedAt: '',
    };
    component.orders.set([newOrder]);
    component.activeFilter.set('active');

    expect(component.filteredOrders()).toEqual([newOrder]);
    expect(component.statusLabel('Received')).toBe('Received');
    expect(component.statusLabel('Washing')).toBe('In Progress');
  });
});
