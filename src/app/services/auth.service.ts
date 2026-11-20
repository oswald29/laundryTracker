import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../environments/environment';

interface AuthResponse {
  token: string;
  expiresAt: string;
  user: {
    id: number;
    fullName: string;
    email: string;
  };
}

const sessionKey = 'freshfold-session';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly authUrl = `${environment.apiUrl}/auth`;
  private readonly http = inject(HttpClient);

  isAuthenticated(): boolean {
    return this.getToken() !== null;
  }

  getToken(): string | null {
    const rawSession = sessionStorage.getItem(sessionKey);
    if (!rawSession) return null;

    try {
      const session: unknown = JSON.parse(rawSession);
      if (
        typeof session === 'object' &&
        session !== null &&
        'token' in session &&
        typeof session.token === 'string' &&
        session.token.length > 0 &&
        'expiresAt' in session &&
        typeof session.expiresAt === 'string' &&
        Date.parse(session.expiresAt) > Date.now()
      ) {
        return session.token;
      }
    } catch {
      sessionStorage.removeItem(sessionKey);
      return null;
    }

    sessionStorage.removeItem(sessionKey);
    return null;
  }

  async login(email: string, password: string): Promise<void> {
    const response = await firstValueFrom(this.http.post<AuthResponse>(`${this.authUrl}/login`, { email, password }));
    this.saveSession(response);
  }

  async signUp(fullName: string, email: string, password: string): Promise<void> {
    const response = await firstValueFrom(
      this.http.post<AuthResponse>(`${this.authUrl}/signup`, { fullName, email, password }),
    );
    this.saveSession(response);
  }

  async logout(): Promise<void> {
    const token = this.getToken();
    try {
      if (token) {
        await firstValueFrom(this.http.post<void>(`${this.authUrl}/logout`, {}));
      }
    } finally {
      this.clearSession();
    }
  }

  clearSession(): void {
    sessionStorage.removeItem(sessionKey);
  }

  private saveSession(response: AuthResponse): void {
    sessionStorage.setItem(sessionKey, JSON.stringify({ token: response.token, expiresAt: response.expiresAt }));
  }
}
