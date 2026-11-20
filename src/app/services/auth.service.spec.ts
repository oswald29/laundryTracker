import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { environment } from '../../environments/environment';

import { authInterceptor } from './auth.interceptor';
import { AuthService } from './auth.service';

describe('AuthService', () => {
  let service: AuthService;
  let http: HttpTestingController;

  const authResponse = {
    token: 'test-token',
    expiresAt: new Date(Date.now() + 60_000).toISOString(),
    user: { id: 1, fullName: 'Test User', email: 'test@example.com' },
  };

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([authInterceptor])), provideHttpClientTesting()],
    });
    service = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    sessionStorage.clear();
  });

  it('creates an account through the API and saves the returned session', async () => {
    const signUp = service.signUp('Test User', 'test@example.com', 'secure-password');
    const request = http.expectOne(`${environment.apiUrl}/auth/signup`);

    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      fullName: 'Test User',
      email: 'test@example.com',
      password: 'secure-password',
    });
    request.flush(authResponse);

    await signUp;
    expect(service.isAuthenticated()).toBe(true);
    expect(service.getToken()).toBe('test-token');
  });

  it('logs in through the API and sends bearer token when logging out', async () => {
    const login = service.login('test@example.com', 'secure-password');
    http.expectOne(`${environment.apiUrl}/auth/login`).flush(authResponse);
    await login;

    const logout = service.logout();
    const request = http.expectOne(`${environment.apiUrl}/auth/logout`);
    expect(request.request.headers.get('Authorization')).toBe('Bearer test-token');
    request.flush({ message: 'Signed out.' });

    await logout;
    expect(service.isAuthenticated()).toBe(false);
  });
});
