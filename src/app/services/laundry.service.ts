import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../environments/environment';

export type OrderStatus = 'Received' | 'Washing' | 'Ready' | 'Completed';
export type LaundryServiceType = 'Wash & Fold' | 'Wash & Iron' | 'Dry Cleaning';

export interface LaundryOrderInput {
  customerName: string;
  phone: string;
  serviceType: LaundryServiceType;
  weightKg: number;
  price: number;
  dueDate: string;
  status: OrderStatus;
}

export interface LaundryOrder extends LaundryOrderInput {
  id: number;
  createdAt: string;
  updatedAt: string;
}

@Injectable({ providedIn: 'root' })
export class LaundryService {
  private readonly ordersUrl = `${environment.apiUrl}/orders`;

  private readonly http = inject(HttpClient);

  getOrders(): Promise<LaundryOrder[]> {
    return firstValueFrom(this.http.get<LaundryOrder[]>(this.ordersUrl));
  }

  createOrder(order: LaundryOrderInput): Promise<LaundryOrder> {
    return firstValueFrom(this.http.post<LaundryOrder>(this.ordersUrl, order));
  }

  updateOrder(id: number, order: LaundryOrderInput): Promise<LaundryOrder> {
    return firstValueFrom(this.http.put<LaundryOrder>(`${this.ordersUrl}/${id}`, order));
  }

  deleteOrder(id: number): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`${this.ordersUrl}/${id}`));
  }
}
