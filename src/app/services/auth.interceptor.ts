import type { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { environment } from '../../environments/environment';

import { AuthService } from './auth.service';

export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const isPublicAuthRequest =
    request.url === `${environment.apiUrl}/auth/login` || request.url === `${environment.apiUrl}/auth/signup`;
  if (!request.url.startsWith(`${environment.apiUrl}/`) || isPublicAuthRequest) {
    return next(request);
  }

  const token = inject(AuthService).getToken();
  return next(token ? request.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : request);
};
