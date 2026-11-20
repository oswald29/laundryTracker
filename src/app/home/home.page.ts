import { CurrencyPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  IonAlert,
  IonButton,
  IonButtons,
  IonCard,
  IonCardContent,
  IonChip,
  IonContent,
  IonHeader,
  IonIcon,
  IonInput,
  IonItem,
  IonLabel,
  IonList,
  IonMenu,
  IonMenuButton,
  IonModal,
  IonNote,
  IonSegment,
  IonSegmentButton,
  IonSelect,
  IonSelectOption,
  IonSpinner,
  IonTitle,
  IonToast,
  IonToolbar,
} from '@ionic/angular';
import { addIcons } from 'ionicons';
import {
  addOutline,
  calendarClearOutline,
  cashOutline,
  checkmarkDoneOutline,
  closeOutline,
  createOutline,
  logOutOutline,
  shirtOutline,
  syncOutline,
  timeOutline,
  trashOutline,
  warningOutline,
  waterOutline,
} from 'ionicons/icons';

import { AuthService } from '../services/auth.service';
import { LaundryService } from '../services/laundry.service';
import type { LaundryOrder, LaundryServiceType, OrderStatus } from '../services/laundry.service';

interface OrderDraft {
  customerName: string;
  phone: string;
  serviceType: LaundryServiceType;
  weightKg: number | string;
  dueDate: string;
}

type ToastColor = 'success' | 'danger' | 'warning';

@Component({
  selector: 'app-home',
  templateUrl: 'home.page.html',
  styleUrls: ['home.page.scss'],
  imports: [
    CurrencyPipe,
    FormsModule,
    IonAlert,
    IonButton,
    IonButtons,
    IonCard,
    IonCardContent,
    IonChip,
    IonContent,
    IonHeader,
    IonIcon,
    IonInput,
    IonItem,
    IonLabel,
    IonList,
    IonMenu,
    IonMenuButton,
    IonModal,
    IonNote,
    IonSegment,
    IonSegmentButton,
    IonSelect,
    IonSelectOption,
    IonSpinner,
    IonTitle,
    IonToast,
    IonToolbar,
  ],
})
export class HomePage {
  readonly orders = signal<LaundryOrder[]>([]);
  readonly isLoading = signal(true);
  readonly isSaving = signal(false);
  readonly errorMessage = signal('');
  readonly activeFilter = signal('all');
  readonly isOrderModalOpen = signal(false);
  readonly isDeleteAlertOpen = signal(false);
  readonly phoneInputError = signal('');
  readonly editingOrderId = signal<number | null>(null);
  readonly toast = signal<{ open: boolean; message: string; color: ToastColor }>({
    open: false,
    message: '',
    color: 'success',
  });
  readonly activeCount = computed(
    () => this.orders().filter((order) => order.status === 'Received' || order.status === 'Washing').length,
  );
  readonly readyCount = computed(() => this.orders().filter((order) => order.status === 'Ready').length);
  readonly completedCount = computed(() => this.orders().filter((order) => order.status === 'Completed').length);
  readonly completedRevenue = computed(() =>
    this.orders()
      .filter((order) => order.status === 'Completed')
      .reduce((total, order) => total + order.price, 0),
  );
  readonly filteredOrders = computed(() => {
    const filter = this.activeFilter();

    return this.orders().filter((order) => {
      const matchesStatus =
        filter === 'all' ||
        (filter === 'active' && (order.status === 'Received' || order.status === 'Washing')) ||
        (filter === 'ready' && order.status === 'Ready') ||
        (filter === 'received' && order.status === 'Received');

      return matchesStatus;
    });
  });

  readonly todayLabel = new Intl.DateTimeFormat('en-PH', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  }).format(new Date());
  readonly deleteAlertButtons = [
    { text: 'Cancel', role: 'cancel' },
    {
      text: 'Delete order',
      role: 'destructive',
      handler: (): void => {
        void this.deleteOrder();
      },
    },
  ];
  draft: OrderDraft = this.emptyDraft();
  private deleteOrderId: number | null = null;
  private editingOrderStatus: OrderStatus = 'Received';

  private readonly laundryService = inject(LaundryService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  constructor() {
    addIcons({
      addOutline,
      calendarClearOutline,
      cashOutline,
      checkmarkDoneOutline,
      closeOutline,
      createOutline,
      logOutOutline,
      shirtOutline,
      syncOutline,
      timeOutline,
      trashOutline,
      warningOutline,
      waterOutline,
    });
    void this.refresh();
  }

  async refresh(): Promise<void> {
    this.isLoading.set(true);
    this.errorMessage.set('');
    try {
      this.orders.set(await this.laundryService.getOrders());
    } catch (error: unknown) {
      if (this.isUnauthorized(error)) {
        this.authService.clearSession();
        await this.router.navigateByUrl('/login', { replaceUrl: true });
      } else {
        this.errorMessage.set('Orders could not be loaded. Please try again.');
      }
    } finally {
      this.isLoading.set(false);
    }
  }

  onFilterChange(event: CustomEvent<{ value?: string | number }>): void {
    const value = event.detail.value;
    this.activeFilter.set(typeof value === 'string' ? value : 'all');
  }

  onPhoneInput(event: CustomEvent<{ value?: string | null }>): void {
    const value = event.detail.value ?? '';
    const digitsOnly = value.replace(/\D/g, '');

    this.draft.phone = digitsOnly;
    this.phoneInputError.set(value === digitsOnly ? '' : 'Phone number can contain numbers only.');
  }

  async logout(): Promise<void> {
    try {
      await this.authService.logout();
    } catch {
      this.authService.clearSession();
    }
    await this.router.navigateByUrl('/login', { replaceUrl: true });
  }

  openNewOrder(): void {
    this.editingOrderId.set(null);
    this.editingOrderStatus = 'Received';
    this.phoneInputError.set('');
    this.draft = this.emptyDraft();
    this.isOrderModalOpen.set(true);
  }

  editOrder(order: LaundryOrder): void {
    this.editingOrderId.set(order.id);
    this.editingOrderStatus = order.status;
    this.phoneInputError.set('');
    this.draft = {
      customerName: order.customerName,
      phone: order.phone,
      serviceType: order.serviceType,
      weightKg: order.weightKg,
      dueDate: order.dueDate,
    };
    this.isOrderModalOpen.set(true);
  }

  closeOrderModal(): void {
    this.isOrderModalOpen.set(false);
  }

  serviceRate(service: LaundryServiceType): number {
    switch (service) {
      case 'Wash & Fold':
        return 45;
      case 'Wash & Iron':
        return 65;
      case 'Dry Cleaning':
        return 120;
    }
  }

  draftPrice(): number {
    const weight = Number.parseFloat(String(this.draft.weightKg));
    return Number.isFinite(weight) ? Math.round(weight * this.serviceRate(this.draft.serviceType) * 100) / 100 : 0;
  }

  async saveOrder(): Promise<void> {
    const customerName = this.draft.customerName.trim();
    const weightKg = Number.parseFloat(String(this.draft.weightKg));
    if (!customerName || !Number.isFinite(weightKg) || weightKg <= 0 || weightKg > 200) {
      this.showToast('Enter a customer name and a weight between 0 and 200 kg.', 'warning');
      return;
    }
    if (this.draft.phone && !/^\d+$/.test(this.draft.phone)) {
      this.phoneInputError.set('Phone number can contain numbers only.');
      return;
    }

    const payload = {
      customerName,
      phone: this.draft.phone.trim(),
      serviceType: this.draft.serviceType,
      weightKg,
      price: this.draftPrice(),
      dueDate: this.draft.dueDate,
      status: this.editingOrderStatus,
    };

    this.isSaving.set(true);
    try {
      const editingId = this.editingOrderId();
      if (editingId === null) {
        await this.laundryService.createOrder(payload);
        this.showToast('Laundry order created.', 'success');
      } else {
        await this.laundryService.updateOrder(editingId, payload);
        this.showToast('Laundry order updated.', 'success');
      }
      this.closeOrderModal();
      await this.refresh();
    } catch (error: unknown) {
      if (this.isUnauthorized(error)) {
        this.authService.clearSession();
        await this.router.navigateByUrl('/login', { replaceUrl: true });
      } else {
        this.showToast('Unable to save the order. Please try again.', 'danger');
      }
    } finally {
      this.isSaving.set(false);
    }
  }

  askToDelete(order: LaundryOrder): void {
    this.deleteOrderId = order.id;
    this.isDeleteAlertOpen.set(true);
  }

  closeToast(): void {
    this.toast.update((current) => ({ ...current, open: false }));
  }

  initials(name: string): string {
    return name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join('');
  }

  avatarClass(name: string): string {
    const colors = ['avatar-blue', 'avatar-green', 'avatar-orange', 'avatar-purple'];
    const seed = name.split('').reduce((sum, character) => sum + character.charCodeAt(0), 0);
    return colors[seed % colors.length];
  }

  statusClass(status: OrderStatus): string {
    return `status-chip status-${status.toLowerCase()}`;
  }

  statusLabel(status: OrderStatus): string {
    return status === 'Washing' ? 'In Progress' : status;
  }

  private async deleteOrder(): Promise<void> {
    const id = this.deleteOrderId;
    this.deleteOrderId = null;
    if (id === null) return;

    try {
      await this.laundryService.deleteOrder(id);
      await this.refresh();
      this.showToast('Laundry order deleted.', 'success');
    } catch (error: unknown) {
      if (this.isUnauthorized(error)) {
        this.authService.clearSession();
        await this.router.navigateByUrl('/login', { replaceUrl: true });
      } else {
        this.showToast('Unable to delete the order. Please try again.', 'danger');
      }
    }
  }

  private emptyDraft(): OrderDraft {
    return {
      customerName: '',
      phone: '',
      serviceType: 'Wash & Fold',
      weightKg: 1,
      dueDate: this.localDateString(),
    };
  }

  private localDateString(): string {
    const date = new Date();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${date.getFullYear()}-${month}-${day}`;
  }

  private showToast(message: string, color: ToastColor): void {
    this.toast.set({ open: true, message, color });
  }

  private isUnauthorized(error: unknown): boolean {
    return error instanceof HttpErrorResponse && error.status === 401;
  }
}
