import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { IonButton, IonCard, IonCardContent, IonContent, IonIcon, IonInput, IonNote, IonSpinner } from '@ionic/angular';
import { addIcons } from 'ionicons';
import { lockClosedOutline, waterOutline } from 'ionicons/icons';

import { AuthService } from '../services/auth.service';

@Component({
  selector: 'app-login',
  templateUrl: './login.page.html',
  styleUrls: ['./login.page.scss'],
  imports: [FormsModule, IonButton, IonCard, IonCardContent, IonContent, IonIcon, IonInput, IonNote, IonSpinner],
})
export class LoginPage {
  fullName = '';
  email = '';
  password = '';
  confirmPassword = '';
  readonly isSignUp = signal(false);
  readonly errorMessage = signal('');
  readonly noticeMessage = signal('');
  readonly isSubmitting = signal(false);

  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  constructor() {
    addIcons({ lockClosedOutline, waterOutline });
    const navigationState = this.router.getCurrentNavigation()?.extras.state;
    if (typeof navigationState?.['logoutWarning'] === 'string') {
      this.noticeMessage.set(navigationState['logoutWarning']);
    }
  }

  async login(): Promise<void> {
    if (!this.email.trim() || !this.password) {
      this.errorMessage.set('Enter an email and password to continue.');
      return;
    }

    await this.enterDashboard(() => this.authService.login(this.email.trim(), this.password));
  }

  async signUp(): Promise<void> {
    if (!this.fullName.trim() || !this.email.trim() || !this.password || !this.confirmPassword) {
      this.errorMessage.set('Complete all fields to continue.');
      return;
    }

    if (this.password.length < 8) {
      this.errorMessage.set('Use a password with at least 8 characters.');
      return;
    }

    if (this.password !== this.confirmPassword) {
      this.errorMessage.set('Passwords do not match.');
      return;
    }

    await this.enterDashboard(() => this.authService.signUp(this.fullName.trim(), this.email.trim(), this.password));
  }

  toggleMode(): void {
    this.isSignUp.update((isSignUp) => !isSignUp);
    this.errorMessage.set('');
  }

  private async enterDashboard(authenticate: () => Promise<void>): Promise<void> {
    this.isSubmitting.set(true);
    this.errorMessage.set('');
    try {
      await authenticate();
      this.password = '';
      this.confirmPassword = '';
      await this.router.navigateByUrl('/home', { replaceUrl: true });
    } catch (error: unknown) {
      this.errorMessage.set(this.describeAuthError(error));
    } finally {
      this.isSubmitting.set(false);
    }
  }

  private describeAuthError(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      if (error.status === 0) return 'Cannot reach the API. Check that the server is running.';
      if (error.status === 401) return 'Invalid email or password.';
      if (error.status === 409) return 'An account with this email already exists.';
      if (typeof error.error?.detail === 'string') return error.error.detail;
      return `The API request failed (HTTP ${error.status}).`;
    }
    return error instanceof Error ? error.message : 'An unexpected error occurred.';
  }
}
