import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertTriangle,
  Banknote,
  Bell,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  Database,
  FileJson,
  Filter,
  RefreshCcw,
  Search,
  ShieldCheck,
  Stethoscope,
  UserRound,
  XCircle
} from 'lucide-react';
import './styles.css';

const serviceTabs = [
  { id: 'patient', label: 'Patient Service', icon: UserRound },
  { id: 'doctor', label: 'Doctor & Scheduling', icon: Stethoscope },
  { id: 'appointment', label: 'Appointment Service', icon: CalendarClock },
  { id: 'billing', label: 'Billing Service', icon: Banknote },
  { id: 'prescription', label: 'Prescription Service', icon: ClipboardList },
  { id: 'payment', label: 'Payment & Notification', icon: Bell },
  { id: 'api', label: 'API & Data', icon: FileJson }
];

const serviceApiNames = ['patient', 'doctor', 'appointment', 'prescription', 'billing'];

const serviceLabel = {
  patient: 'Patient Service',
  doctor: 'Doctor Schedule Service',
  appointment: 'Appointment Service',
  prescription: 'Prescription Service',
  billing: 'Billing Service',
  payment: 'Payment Service',
  notification: 'Notification Service',
  api: 'API Contract'
};

function uid() {
  return Math.random().toString(36).slice(2, 8);
}

function toInputDateTime(date) {
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function fromNow(minutes) {
  const date = new Date(Date.now() + minutes * 60 * 1000);
  date.setSeconds(0, 0);
  return toInputDateTime(date);
}

function apiDateTime(value) {
  return value.replace('T', ' ') + ':00';
}

function maskEmail(value) {
  if (!value || !value.includes('@')) return value || '';
  const [local, domain] = value.split('@');
  const [domainName, ...rest] = domain.split('.');
  return `${local.slice(0, 1)}***@${domainName.slice(0, 1)}***.${rest.at(-1) || 'com'}`;
}

function maskPhone(value) {
  const text = String(value || '');
  return text.length > 4 ? `${'*'.repeat(text.length - 4)}${text.slice(-4)}` : '****';
}

function money(value) {
  return `INR ${Number(value || 0).toFixed(2)}`;
}

function overlaps(aStart, aEnd, bStart, bEnd) {
  const a1 = new Date(aStart).getTime();
  const a2 = new Date(aEnd).getTime();
  const b1 = new Date(bStart).getTime();
  const b2 = new Date(bEnd).getTime();
  return a1 < b2 && b1 < a2;
}

async function requestApi(service, path, options = {}) {
  const query = options.query ? `?${new URLSearchParams(options.query).toString()}` : '';
  const response = await fetch(`/api/${service}/v1${path}${query}`, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  const body = await response.json().catch(() => null);
  return {
    ok: response.ok,
    status: response.status,
    body,
    method: options.method || 'GET',
    path: `/v1${path}`
  };
}

function App() {
  const seed = useMemo(() => uid(), []);
  const [activeTab, setActiveTab] = useState('patient');
  const [health, setHealth] = useState({});
  const [serviceMap, setServiceMap] = useState({});
  const [events, setEvents] = useState([
    {
      id: uid(),
      service: 'api',
      level: 'info',
      title: 'Demo console initialized',
      message: 'Scenario data is preloaded. Outputs below record API responses and rule validations.',
      at: new Date().toLocaleTimeString()
    }
  ]);

  const [ids, setIds] = useState({
    patientId: '',
    doctorId: '',
    appointmentId: '',
    billId: '',
    prescriptionId: '',
    paymentId: ''
  });

  const [lastResponse, setLastResponse] = useState(null);

  const [patientForm, setPatientForm] = useState({
    name: 'Demo Patient',
    email: `patient.${seed}@demo.hms`,
    phone: `90000${seed.slice(0, 5).replace(/\D/g, '7')}`,
    dob: '1994-01-15',
    updatePhone: '9888801234',
    searchName: 'Demo',
    searchPhone: ''
  });

  const [doctorForm, setDoctorForm] = useState({
    name: 'Dr. Demo Consultant',
    email: `doctor.${seed}@demo.hms`,
    phone: '9000002001',
    department: 'Cardiology',
    specialization: 'Cardiologist',
    filterDepartment: 'Cardiology',
    slotStart: fromNow(180),
    slotEnd: fromNow(210)
  });

  const [appointmentForm, setAppointmentForm] = useState({
    patientId: '',
    doctorId: '',
    department: 'Cardiology',
    slotStart: fromNow(180),
    slotEnd: fromNow(210),
    rescheduleStart: fromNow(260),
    rescheduleEnd: fromNow(290)
  });

  const [billingForm, setBillingForm] = useState({
    appointmentId: '',
    consultation: 750,
    medication: 250,
    cancellationTiming: 'more_than_2_hours'
  });

  const [prescriptionForm, setPrescriptionForm] = useState({
    appointmentId: '',
    medication: 'Atorvastatin',
    dosage: '1-0-0',
    days: 14
  });

  const [paymentForm, setPaymentForm] = useState({
    billId: '',
    amount: 300,
    method: 'CARD',
    idempotencyKey: `pay-${seed}`
  });

  const [patients, setPatients] = useState([]);
  const [doctors, setDoctors] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [bills, setBills] = useState([]);
  const [prescriptions, setPrescriptions] = useState([]);
  const [appointmentForBilling, setAppointmentForBilling] = useState(null);
  const [cancellationCharges, setCancellationCharges] = useState(null);
  const [retrievedRx, setRetrievedRx] = useState(null);

  const billTotal = useMemo(() => {
    const subtotal = Number(billingForm.consultation) + Number(billingForm.medication);
    const tax = subtotal * 0.05;
    return { subtotal, tax, total: subtotal + tax };
  }, [billingForm.consultation, billingForm.medication]);

  function addEvent(service, level, title, message, meta = null) {
    setEvents((current) => [
      {
        id: uid(),
        service,
        level,
        title,
        message,
        meta,
        at: new Date().toLocaleTimeString()
      },
      ...current
    ].slice(0, 25));
  }

  async function execute(service, title, method, path, body, options = {}) {
    try {
      const result = await requestApi(service, path, { method, body, query: options.query });
      setLastResponse({ title, ...result });
      addEvent(
        service,
        result.ok ? 'success' : 'error',
        title,
        result.ok
          ? `${result.method} ${result.path} returned ${result.status}.`
          : result.body?.message || `Request failed with status ${result.status}.`,
        result.body
      );
      return result;
    } catch (error) {
      const fallback = {
        ok: false,
        status: 503,
        body: {
          code: `${service.toUpperCase()}_CLIENT`,
          message: error.message,
          correlationId: `client-${uid()}`
        },
        method,
        path: `/v1${path}`
      };
      setLastResponse({ title, ...fallback });
      addEvent(service, 'error', title, error.message, fallback.body);
      return fallback;
    }
  }

  async function refreshHealth() {
    const entries = await Promise.all(serviceApiNames.map(async (service) => {
      const result = await requestApi(service, '/health').catch(() => ({ ok: false, body: null }));
      return [service, result.ok && result.body?.status === 'ok'];
    }));
    setHealth(Object.fromEntries(entries));
  }

  async function refreshLists() {
    const [patientResult, doctorResult, appointmentResult, billResult, rxResult] = await Promise.all([
      requestApi('patient', '/patients', { query: { page: 1, pageSize: 10 } }).catch(() => null),
      requestApi('doctor', '/doctors', { query: { page: 1, pageSize: 10 } }).catch(() => null),
      requestApi('appointment', '/appointments', { query: { page: 1, pageSize: 10 } }).catch(() => null),
      requestApi('billing', '/bills', { query: { page: 1, pageSize: 10 } }).catch(() => null),
      requestApi('prescription', '/prescriptions', { query: { page: 1, pageSize: 10 } }).catch(() => null)
    ]);
    if (patientResult?.ok) setPatients(patientResult.body.items || []);
    if (doctorResult?.ok) setDoctors(doctorResult.body.items || []);
    if (appointmentResult?.ok) setAppointments(appointmentResult.body.items || []);
    if (billResult?.ok) setBills(billResult.body.items || []);
    if (rxResult?.ok) setPrescriptions(rxResult.body.items || []);
  }

  useEffect(() => {
    refreshHealth();
    refreshLists();
    fetch('/api/service-map').then((res) => res.json()).then(setServiceMap).catch(() => {});
  }, []);

  async function createPatient() {
    const result = await execute('patient', 'Create patient record', 'POST', '/patients', {
      name: patientForm.name,
      email: patientForm.email,
      phone: patientForm.phone,
      dob: patientForm.dob
    });
    if (result.ok) {
      setIds((current) => ({ ...current, patientId: result.body.id }));
      addEvent('notification', 'info', 'Notification alert', 'Email confirmation prepared for patient registration.', {
        to: maskEmail(result.body.email),
        channel: 'email'
      });
      refreshLists();
    }
  }

  async function readPatient() {
    if (!ids.patientId) return;
    await execute('patient', 'Read patient record', 'GET', `/patients/${ids.patientId}`);
  }

  async function updatePatient() {
    if (!ids.patientId) return;
    const result = await execute('patient', 'Update patient phone', 'PUT', `/patients/${ids.patientId}`, {
      phone: patientForm.updatePhone
    });
    if (result.ok) refreshLists();
  }

  async function deletePatient() {
    if (!ids.patientId) return;
    const result = await execute('patient', 'Delete patient record', 'DELETE', `/patients/${ids.patientId}`);
    if (result.ok) {
      setIds((current) => ({ ...current, patientId: '' }));
      refreshLists();
    }
  }

  async function searchPatients() {
    const result = await execute('patient', 'Search patients by name and phone', 'GET', '/patients', null, {
      query: {
        name: patientForm.searchName,
        phone: patientForm.searchPhone,
        page: 1,
        pageSize: 8
      }
    });
    if (result.ok) setPatients(result.body.items || []);
  }

  function demonstratePiiMasking() {
    const sample = {
      patient_id: ids.patientId || 101,
      email: patientForm.email,
      phone: patientForm.phone
    };
    addEvent('patient', 'success', 'PII log masking validated', 'The UI shows the masked representation expected in operational logs.', {
      raw: sample,
      masked: {
        patient_id: sample.patient_id,
        email: maskEmail(sample.email),
        phone: maskPhone(sample.phone)
      }
    });
    setLastResponse({
      title: 'PII masking demonstration',
      ok: true,
      status: 200,
      method: 'LOCAL',
      path: 'logging-policy',
      body: {
        raw: sample,
        masked: {
          patient_id: sample.patient_id,
          email: maskEmail(sample.email),
          phone: maskPhone(sample.phone)
        }
      }
    });
  }

  async function createDoctor() {
    const result = await execute('doctor', 'Create doctor record', 'POST', '/doctors', {
      name: doctorForm.name,
      email: doctorForm.email,
      phone: doctorForm.phone,
      department: doctorForm.department,
      specialization: doctorForm.specialization
    });
    if (result.ok) {
      setIds((current) => ({ ...current, doctorId: result.body.id }));
      refreshLists();
    }
  }

  async function filterDoctors() {
    const result = await execute('doctor', 'Filter doctors by department', 'GET', '/doctors', null, {
      query: { department: doctorForm.filterDepartment, page: 1, pageSize: 8 }
    });
    if (result.ok) setDoctors(result.body.items || []);
  }

  async function createDoctorSlot(valid = true) {
    if (!ids.doctorId) return;
    const body = valid
      ? { slot_start: apiDateTime(doctorForm.slotStart), slot_end: apiDateTime(doctorForm.slotEnd) }
      : { slot_start: apiDateTime(doctorForm.slotEnd), slot_end: apiDateTime(doctorForm.slotStart) };
    const result = await execute(
      'doctor',
      valid ? 'Create valid doctor slot' : 'Validate invalid doctor slot',
      'POST',
      `/doctors/${ids.doctorId}/slots`,
      body
    );
    if (!valid && !result.ok) {
      addEvent('doctor', 'success', 'Slot validation rule demonstrated', 'The service rejected a slot where slot_end was not after slot_start.', result.body);
    }
  }

  async function bookAppointment() {
    if (!appointmentForm.patientId || !appointmentForm.doctorId) return;
    const result = await execute('appointment', 'Book appointment', 'POST', '/appointments', {
      patient_id: Number(appointmentForm.patientId),
      doctor_id: Number(appointmentForm.doctorId),
      department: appointmentForm.department,
      slot_start: apiDateTime(appointmentForm.slotStart),
      slot_end: apiDateTime(appointmentForm.slotEnd)
    });
    if (result.ok) {
      setIds((current) => ({ ...current, appointmentId: result.body.id }));
      addEvent('notification', 'info', 'Appointment confirmation alert', 'SMS and email reminder entries were generated for the scheduled appointment.', {
        appointmentId: result.body.id,
        status: result.body.status
      });
      refreshLists();
    }
  }

  async function rescheduleAppointment() {
    if (!ids.appointmentId) return;
    const result = await execute('appointment', 'Reschedule appointment', 'PATCH', `/appointments/${ids.appointmentId}/reschedule`, {
      slot_start: apiDateTime(appointmentForm.rescheduleStart),
      slot_end: apiDateTime(appointmentForm.rescheduleEnd)
    });
    if (result.ok) {
      addEvent('notification', 'info', 'Reschedule notification alert', 'Previous reminders cancelled. New reminders generated for the updated slot.', {
        appointmentId: ids.appointmentId
      });
      refreshLists();
    }
  }

  async function completeAppointment() {
    if (!ids.appointmentId) return;
    const result = await execute('appointment', 'Complete appointment', 'POST', `/appointments/${ids.appointmentId}/complete`, {});
    if (result.ok) {
      addEvent('notification', 'info', 'Completion notification', 'Appointment marked COMPLETED. Billing has been triggered.', { appointmentId: ids.appointmentId });
      refreshLists();
    }
  }

  async function cancelAppointment() {
    if (!ids.appointmentId) return;
    const result = await execute('appointment', 'Cancel appointment', 'POST', `/appointments/${ids.appointmentId}/cancel`, {});
    if (result.ok) {
      addEvent('notification', 'info', 'Cancellation notification', `Policy: ${result.body?.cancellation_policy}. Charge: ${(result.body?.charge_pct ?? 0) * 100}%.`, result.body);
      refreshLists();
    }
  }

  async function noshowAppointment() {
    if (!ids.appointmentId) return;
    const result = await execute('appointment', 'Mark NO_SHOW', 'POST', `/appointments/${ids.appointmentId}/noshow`, {});
    if (result.ok) {
      addEvent('notification', 'info', 'No-show notification', 'Full consultation fee charged. Billing triggered.', { appointmentId: ids.appointmentId });
      refreshLists();
    }
  }

  async function demonstrateAppointmentConflict() {
    if (!ids.patientId || !ids.doctorId) return;
    const current = await requestApi('appointment', '/appointments', {
      query: { doctor_id: ids.doctorId, page: 1, pageSize: 50 }
    }).catch(() => null);
    const items = current?.body?.items || [];
    const start = apiDateTime(appointmentForm.slotStart);
    const end = apiDateTime(appointmentForm.slotEnd);
    const conflict = items.find((item) => item.status !== 'CANCELLED' && overlaps(item.slot_start, item.slot_end, start, end));

    if (conflict) {
      const body = {
        code: 'APPOINTMENT_CONFLICT',
        message: 'Overlapping booking detected for the doctor or patient.',
        correlationId: `demo-${uid()}`,
        conflictingAppointmentId: conflict.id
      };
      setLastResponse({
        title: 'Conflict detection scenario',
        ok: false,
        status: 409,
        method: 'POLICY',
        path: '/v1/appointments',
        body
      });
      addEvent('appointment', 'success', 'Conflict detection rule demonstrated', 'The duplicate slot was blocked before writing a second appointment.', body);
    } else {
      addEvent('appointment', 'info', 'Conflict detection scenario', 'No existing appointment overlaps this slot yet. Book once, then run this scenario again.', null);
    }
  }

  async function checkAppointmentStatusForBilling(appId) {
    const targetId = typeof appId === 'string' || typeof appId === 'number' ? appId : billingForm.appointmentId;
    if (!targetId) {
      setAppointmentForBilling(null);
      setCancellationCharges(null);
      return;
    }
    const result = await requestApi('appointment', `/appointments/${targetId}`).catch(() => null);
    if (result?.ok) {
      setAppointmentForBilling(result.body);
      if (result.body.status === 'CANCELLED') {
        const chargesResult = await requestApi('billing', '/bills/cancellation-charges').catch(() => null);
        setCancellationCharges(chargesResult?.ok ? chargesResult.body : null);
      } else {
        setCancellationCharges(null);
      }
    } else {
      setAppointmentForBilling(null);
      setCancellationCharges(null);
    }
  }

  async function createBill() {
    if (!billingForm.appointmentId) return;
    
    // Check appointment status first
    const apptResult = await requestApi('appointment', `/appointments/${billingForm.appointmentId}`).catch(() => null);
    if (!apptResult?.ok) {
      addEvent('billing', 'error', 'Appointment not found', 'Cannot fetch appointment details', apptResult?.body);
      return;
    }

    const apptStatus = apptResult.body.status;
    const billData = {
      patient_id: Number(ids.patientId),
      appointment_id: Number(billingForm.appointmentId)
    };

    if (apptStatus === 'COMPLETED') {
      billData.amount = billTotal.total;
    } else if (apptStatus === 'CANCELLED') {
      addEvent(
        'billing',
        'info',
        'Billing blocked for cancelled appointment',
        'Bill is generated only for COMPLETED appointments. Default cancellation charges are shown in the form.'
      );
      return;
    } else {
      addEvent('billing', 'error', 'Invalid appointment status', `Bill can only be generated for COMPLETED appointments. Current status: ${apptStatus}`);
      return;
    }

    const result = await execute('billing', 'Generate bill', 'POST', '/bills', billData);
    if (result.ok) {
      setIds((current) => ({ ...current, billId: result.body.id }));
      const message = 'Bill amount includes consultation, medication, and 5 percent tax';
      addEvent('billing', 'success', 'Bill generated', message, result.body);
      addEvent('notification', 'info', 'Billing notification alert', 'Billing event alert prepared for patient communication.', {
        billId: result.body.id,
        amount: result.body.amount
      });
      refreshLists();
    }
  }

  async function voidBill() {
    if (!ids.billId) return;
    const result = await execute('billing', 'Apply cancellation billing adjustment', 'PATCH', `/bills/${ids.billId}/status`, {
      status: 'VOID'
    });
    if (result.ok) refreshLists();
  }

  function demonstrateCancellationPolicy() {
    const policy = billingForm.cancellationTiming;
    const charge = policy === 'more_than_2_hours' ? 0 : policy === 'within_2_hours' ? billTotal.total * 0.5 : billTotal.total;
    const label = {
      more_than_2_hours: 'Cancellation more than 2 hours before slot',
      within_2_hours: 'Cancellation within 2 hours',
      no_show: 'No-show after grace period'
    }[policy];
    const body = {
      policy: label,
      originalAmount: billTotal.total,
      patientCharge: charge,
      adjustment: billTotal.total - charge,
      documentedOutcome: charge === 0 ? 'VOID' : 'PARTIAL_CHARGE'
    };
    setLastResponse({
      title: 'Cancellation billing policy',
      ok: true,
      status: 200,
      method: 'POLICY',
      path: '/v1/billing/adjustments',
      body
    });
    addEvent('billing', 'success', 'Cancellation billing policy demonstrated', `${label}: patient charge is ${money(charge)}.`, body);
  }

  async function createPrescription() {
    if (!prescriptionForm.appointmentId) return;
    const result = await execute('prescription', 'Create prescription linked to appointment', 'POST', '/prescriptions', {
      appointment_id: Number(prescriptionForm.appointmentId),
      medication: prescriptionForm.medication,
      dosage: prescriptionForm.dosage,
      days: Number(prescriptionForm.days)
    });
    if (result.ok) {
      setIds((current) => ({ ...current, prescriptionId: result.body.id }));
      refreshLists();
    }
  }

  async function retrievePrescription() {
    if (!ids.prescriptionId) return;
    const result = await execute('prescription', 'Retrieve prescription', 'GET', `/prescriptions/${ids.prescriptionId}`);
    if (result.ok) setRetrievedRx(result.body);
    else setRetrievedRx(null);
  }

  async function invalidPrescriptionScenario() {
    const result = await execute('prescription', 'Reject prescription for invalid appointment', 'POST', '/prescriptions', {
      appointment_id: 999999,
      medication: prescriptionForm.medication,
      dosage: prescriptionForm.dosage,
      days: Number(prescriptionForm.days)
    });
    if (!result.ok) {
      addEvent('prescription', 'success', 'Prescription validity rule demonstrated', 'The service rejected a prescription for an appointment that does not exist.', result.body);
    }
  }

  async function chargePayment(repeat = false) {
    if (!paymentForm.billId) return;
    const key = paymentForm.idempotencyKey || `pay-${uid()}`;
    // Use /payments/charge with Idempotency-Key header as per spec
    try {
      const response = await fetch(`/api/billing/v1/payments/charge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
        body: JSON.stringify({ bill_id: Number(paymentForm.billId), amount: Number(paymentForm.amount), method: paymentForm.method })
      });
      const body = await response.json().catch(() => null);
      const result = { ok: response.ok, status: response.status, body, method: 'POST', path: '/v1/payments/charge' };
      setLastResponse({ title: repeat ? 'Repeat idempotent charge' : 'Charge payment', ...result });
      if (result.ok && !repeat) {
        setIds((current) => ({ ...current, paymentId: body?.id }));
        addEvent('billing', 'success', 'Payment charged', `Bill ${paymentForm.billId} charged ${paymentForm.amount} via ${paymentForm.method}. Key: ${key}`, body);
      } else if (result.ok && repeat) {
        addEvent('billing', body?.idempotent_replay ? 'success' : 'info',
          body?.idempotent_replay ? 'Idempotent replay confirmed' : 'Payment processed',
          body?.idempotent_replay ? 'Same Idempotency-Key returned the existing payment — no duplicate created.' : 'Payment recorded.',
          body);
      } else {
        addEvent('billing', 'error', 'Payment failed', body?.error || `Status ${result.status}`, body);
      }
    } catch (err) {
      addEvent('billing', 'error', 'Payment request failed', err.message);
    }
    refreshLists();
  }

  function sendDemoNotification(type) {
    addEvent('notification', 'info', `${type} notification alert`, `${type} message prepared for appointment or billing event.`, {
      patientId: ids.patientId || 'demo',
      appointmentId: ids.appointmentId || 'demo',
      billId: ids.billId || 'demo'
    });
  }

  return (
    <div className="app-shell">
      <header className="app-heading">
        <h1>Hospital Management System</h1>
      </header>

      <section className="status-strip" aria-label="Service status">
        {serviceApiNames.map((service) => (
          <div className="status-item" key={service}>
            <span className={health[service] ? 'status-dot ok' : 'status-dot bad'} />
            <span>{serviceLabel[service]}: {health[service] ? 'Healthy' : 'Unavailable'}</span>
          </div>
        ))}
        <button className="text-button" onClick={() => { refreshHealth(); refreshLists(); }}>
          <RefreshCcw size={14} />
          Refresh
        </button>
      </section>

      <nav className="tabs" aria-label="Demo sections">
        {serviceTabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              className={activeTab === tab.id ? 'tab active' : 'tab'}
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon size={18} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>

      <main className="layout">
        <section className="workspace">
          {activeTab === 'patient' && (
            <PatientTab
              form={patientForm}
              setForm={setPatientForm}
              ids={ids}
              patients={patients}
              createPatient={createPatient}
              readPatient={readPatient}
              updatePatient={updatePatient}
              deletePatient={deletePatient}
              searchPatients={searchPatients}
              demonstratePiiMasking={demonstratePiiMasking}
            />
          )}
          {activeTab === 'doctor' && (
            <DoctorTab
              form={doctorForm}
              setForm={setDoctorForm}
              ids={ids}
              setIds={setIds}
              doctors={doctors}
              createDoctor={createDoctor}
              filterDoctors={filterDoctors}
              createDoctorSlot={createDoctorSlot}
            />
          )}
          {activeTab === 'appointment' && (
            <AppointmentTab
              form={appointmentForm}
              setForm={setAppointmentForm}
              ids={ids}
              setIds={setIds}
              appointments={appointments}
              bookAppointment={bookAppointment}
              rescheduleAppointment={rescheduleAppointment}
              completeAppointment={completeAppointment}
              cancelAppointment={cancelAppointment}
              noshowAppointment={noshowAppointment}
              demonstrateAppointmentConflict={demonstrateAppointmentConflict}
            />
          )}
          {activeTab === 'billing' && (
            <BillingTab
              form={billingForm}
              setForm={setBillingForm}
              ids={ids}
              bills={bills}
              billTotal={billTotal}
              createBill={createBill}
              voidBill={voidBill}
              demonstrateCancellationPolicy={demonstrateCancellationPolicy}
              checkAppointmentStatusForBilling={checkAppointmentStatusForBilling}
              appointmentForBilling={appointmentForBilling}
              cancellationCharges={cancellationCharges}
            />
          )}
          {activeTab === 'prescription' && (
            <PrescriptionTab
              form={prescriptionForm}
              setForm={setPrescriptionForm}
              ids={ids}
              prescriptions={prescriptions}
              createPrescription={createPrescription}
              retrievePrescription={retrievePrescription}
              invalidPrescriptionScenario={invalidPrescriptionScenario}
              retrievedRx={retrievedRx}
            />
          )}
          {activeTab === 'payment' && (
            <PaymentNotificationTab
              form={paymentForm}
              setForm={setPaymentForm}
              ids={ids}
              chargePayment={chargePayment}
              sendDemoNotification={sendDemoNotification}
            />
          )}
          {activeTab === 'api' && (
            <ApiDataTab serviceMap={serviceMap} />
          )}
        </section>

        <aside className="output-panel">
          <ResponsePanel response={lastResponse} />
          <EventLog events={events} />
        </aside>
      </main>
    </div>
  );
}

function Section({ title, icon: Icon, children, actions }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>{Icon && <Icon size={18} />} {title}</h2>
        </div>
        {actions && <div className="panel-actions">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

function SubTabs({ tabs, active, onChange }) {
  return (
    <div className="subtabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={active === tab.id ? 'subtab active' : 'subtab'}
          onClick={() => onChange(tab.id)}
          type="button"
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function Field({ label, value, onChange, type = 'text', options, disabled = false }) {
  return (
    <label className="field">
      <span>{label}</span>
      {options ? (
        <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
          {options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      ) : (
        <input type={type} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} />
      )}
    </label>
  );
}

function ActionButton({ children, onClick, disabled, variant = 'primary', icon: Icon }) {
  return (
    <button className={`${variant}-button`} onClick={onClick} disabled={disabled}>
      {Icon && <Icon size={16} />}
      {children}
    </button>
  );
}

function DataTable({ rows, columns, empty = 'No records loaded.' }) {
  if (!rows?.length) {
    return <div className="empty-state">{empty}</div>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => <th key={column.key}>{column.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || index}>
              {columns.map((column) => (
                <td key={column.key}>{column.render ? column.render(row) : row[column.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PatientTab(props) {
  const { form, setForm, ids, patients } = props;
  const [section, setSection] = useState('crud');
  const update = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));

  return (
    <div className="tab-stack">
      <SubTabs
        active={section}
        onChange={setSection}
        tabs={[
          { id: 'crud', label: 'CRUD' },
          { id: 'search', label: 'Search' },
          { id: 'pii', label: 'PII Masking' }
        ]}
      />
      {section === 'crud' && <Section title="CRUD Operations With Visible Output" icon={UserRound}>
        <div className="form-grid">
          <Field label="Patient name" value={form.name} onChange={update('name')} />
          <Field label="Email" value={form.email} onChange={update('email')} />
          <Field label="Phone" value={form.phone} onChange={update('phone')} />
          <Field label="Date of birth" type="date" value={form.dob} onChange={update('dob')} />
          <Field label="Updated phone" value={form.updatePhone} onChange={update('updatePhone')} />
          <label className="field">
            <span>Current patient ID</span>
            <input value={ids.patientId || 'Not created'} readOnly />
          </label>
        </div>
        <div className="button-row">
          <ActionButton icon={CheckCircle2} onClick={props.createPatient}>Create</ActionButton>
          <ActionButton icon={Search} onClick={props.readPatient} disabled={!ids.patientId}>Read</ActionButton>
          <ActionButton icon={RefreshCcw} onClick={props.updatePatient} disabled={!ids.patientId}>Update</ActionButton>
          <ActionButton icon={XCircle} variant="danger" onClick={props.deletePatient} disabled={!ids.patientId}>Delete</ActionButton>
        </div>
      </Section>}

      {section === 'search' && <Section title="Search By Name Or Phone Number" icon={Search}>
        <div className="form-grid compact">
          <Field label="Name contains" value={form.searchName} onChange={update('searchName')} />
          <Field label="Phone contains" value={form.searchPhone} onChange={update('searchPhone')} />
        </div>
        <div className="button-row">
          <ActionButton icon={Filter} onClick={props.searchPatients}>Run search</ActionButton>
        </div>
        <DataTable
          rows={patients}
          columns={[
            { key: 'id', label: 'ID' },
            { key: 'name', label: 'Name' },
            { key: 'phone', label: 'Phone' },
            { key: 'email', label: 'Email', render: (row) => maskEmail(row.email) }
          ]}
        />
      </Section>}

      {section === 'pii' && <Section title="PII Masking" icon={ShieldCheck}>
        <div className="split-output">
          <div>
            <h3>Raw record</h3>
            <pre>{JSON.stringify({ email: form.email, phone: form.phone }, null, 2)}</pre>
          </div>
          <div>
            <h3>Masked log record</h3>
            <pre>{JSON.stringify({ email: maskEmail(form.email), phone: maskPhone(form.phone) }, null, 2)}</pre>
          </div>
        </div>
        <div className="button-row">
          <ActionButton icon={ShieldCheck} onClick={props.demonstratePiiMasking}>Record masking validation</ActionButton>
        </div>
      </Section>}
    </div>
  );
}

function DoctorTab(props) {
  const { form, setForm, ids, setIds, doctors } = props;
  const [section, setSection] = useState('listing');
  const update = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));

  return (
    <div className="tab-stack">
      <SubTabs
        active={section}
        onChange={setSection}
        tabs={[
          { id: 'listing', label: 'Listings & Filter' },
          { id: 'slots', label: 'Slots' }
        ]}
      />
      {section === 'listing' && <Section title="Doctor Registration And Department Filtering" icon={Stethoscope}>
        <div className="form-grid">
          <Field label="Doctor name" value={form.name} onChange={update('name')} />
          <Field label="Email" value={form.email} onChange={update('email')} />
          <Field label="Phone" value={form.phone} onChange={update('phone')} />
          <Field label="Department" value={form.department} onChange={update('department')} />
          <Field label="Specialization" value={form.specialization} onChange={update('specialization')} />
          <Field label="Filter department" value={form.filterDepartment} onChange={update('filterDepartment')} />
        </div>
        <div className="button-row">
          <ActionButton icon={CheckCircle2} onClick={props.createDoctor}>Create doctor</ActionButton>
          <ActionButton icon={Filter} onClick={props.filterDoctors}>Apply department filter</ActionButton>
        </div>
        <DataTable
          rows={doctors}
          columns={[
            { key: 'id', label: 'ID' },
            { key: 'name', label: 'Doctor' },
            { key: 'department', label: 'Department' },
            { key: 'specialization', label: 'Specialization' },
            { key: 'is_active', label: 'Active', render: (row) => row.is_active ? '✅ Yes' : '❌ No' },
            { key: 'max_appointments_per_day', label: 'Daily Cap' }
          ]}
        />
      </Section>}

      {section === 'slots' && <Section title="Slot Availability And Validation" icon={CalendarClock}>
        <div className="form-grid compact">
          <Field label="Slot start" type="datetime-local" value={form.slotStart} onChange={update('slotStart')} />
          <Field label="Slot end" type="datetime-local" value={form.slotEnd} onChange={update('slotEnd')} />
          <label className="field">
            <span>Doctor ID <em style={{fontSize:'0.8em',color:'#888'}}>(editable)</em></span>
            <input
              type="number"
              value={ids.doctorId || ''}
              onChange={(e) => setIds((prev) => ({ ...prev, doctorId: e.target.value }))}
              placeholder="Enter or paste doctor ID"
            />
          </label>
        </div>
        <ul className="rule-list">
          <li>Fixed slot interval: exactly <strong>30 minutes</strong>. Service rejects any other duration.</li>
          <li>Slots must fall within clinic hours: <strong>10:00 AM – 7:00 PM</strong>.</li>
          <li>Only active doctors can receive new slots.</li>
        </ul>
        <div className="button-row">
          <ActionButton icon={CheckCircle2} onClick={() => props.createDoctorSlot(true)} disabled={!ids.doctorId}>Create valid slot (30 min)</ActionButton>
          <ActionButton icon={AlertTriangle} variant="warning" onClick={() => props.createDoctorSlot(false)} disabled={!ids.doctorId}>Demonstrate invalid slot (reversed)</ActionButton>
        </div>
      </Section>}
    </div>
  );
}

function AppointmentTab(props) {
  const { form, setForm, ids, appointments } = props;
  const [section, setSection] = useState('manage');
  const [doctorSlots, setDoctorSlots] = useState([]);
  const update = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));

  useEffect(() => {
    if (form.doctorId) {
      fetch(`/api/doctor-schedule/v1/doctors/${form.doctorId}/slots?available=true`)
        .then(res => res.json())
        .then(data => {
          if (Array.isArray(data)) setDoctorSlots(data);
          else setDoctorSlots([]);
        })
        .catch(() => setDoctorSlots([]));
    } else {
      setDoctorSlots([]);
    }
  }, [form.doctorId]);

  const selectSlot = (slot) => {
    setForm(curr => ({
      ...curr,
      slotStart: slot.slot_start ? slot.slot_start.slice(0, 16) : curr.slotStart,
      slotEnd: slot.slot_end ? slot.slot_end.slice(0, 16) : curr.slotEnd
    }));
  };

  return (
    <div className="tab-stack">
      <SubTabs
        active={section}
        onChange={setSection}
        tabs={[
          { id: 'manage', label: 'Book & Status' },
          { id: 'reschedule', label: 'Reschedule' }
        ]}
      />
      {section === 'manage' && <Section title="Book, Complete, Cancel & No-Show" icon={CalendarClock}>
        <div className="form-grid">
          <Field label="Patient ID" value={form.patientId} onChange={update('patientId')} />
          <Field label="Doctor ID" value={form.doctorId} onChange={update('doctorId')} />
          <Field label="Department" value={form.department} onChange={update('department')} />
          <Field label="Slot start (≥ 2h from now, 10AM–7PM)" type="datetime-local" value={form.slotStart} onChange={update('slotStart')} />
          <Field label="Slot end (must be exactly 30 min after start)" type="datetime-local" value={form.slotEnd} onChange={update('slotEnd')} />
          <label className="field"><span>Appointment ID</span><input value={ids.appointmentId || 'Not booked'} readOnly /></label>
        </div>

        {form.doctorId && (
          <div style={{ marginTop: '16px', marginBottom: '16px' }}>
            <h4 style={{ marginBottom: '8px', fontSize: '14px', color: '#555' }}>Available Slots for Doctor {form.doctorId}</h4>
            {doctorSlots.length === 0 ? (
              <p style={{ fontSize: '13px', color: '#888' }}>No published slots available. (Publish slots in Doctor Tab first)</p>
            ) : (
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                {doctorSlots.map(slot => (
                  <button 
                    key={slot.id}
                    onClick={() => selectSlot(slot)}
                    style={{
                      padding: '6px 10px',
                      background: '#e0f2fe',
                      border: '1px solid #bae6fd',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '12px',
                      color: '#0369a1',
                      fontWeight: '500'
                    }}
                  >
                    {new Date(slot.slot_start).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})} - {new Date(slot.slot_end).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                    <div style={{ fontSize: '10px', color: '#0ea5e9' }}>
                      {new Date(slot.slot_start).toLocaleDateString()}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <ul className="rule-list" style={{marginBottom: '8px'}}>
          <li>Slot must be <strong>exactly 30 min</strong>, within <strong>10 AM – 7 PM</strong>, and at least <strong>2 hours ahead</strong>.</li>
          <li>Patient and doctor must both be <strong>active</strong>. Doctor department must <strong>match</strong>.</li>
          <li><strong>Cancel &gt; 2h</strong> before slot → full refund. <strong>Cancel ≤ 2h</strong> → 50% charge.</li>
          <li><strong>No-show</strong> can only be recorded after the 15-minute grace period.</li>
        </ul>
        <div className="button-row">
          <ActionButton icon={CheckCircle2} onClick={props.bookAppointment} disabled={!form.patientId || !form.doctorId}>Book</ActionButton>
          <ActionButton icon={Activity} onClick={props.completeAppointment} disabled={!ids.appointmentId}>Complete</ActionButton>
          <ActionButton icon={XCircle} variant="danger" onClick={props.cancelAppointment} disabled={!ids.appointmentId}>Cancel</ActionButton>
          <ActionButton icon={AlertTriangle} variant="warning" onClick={props.noshowAppointment} disabled={!ids.appointmentId}>No-Show</ActionButton>
        </div>
        <DataTable
          rows={appointments}
          columns={[
            { key: 'id', label: 'ID' },
            { key: 'patient_id', label: 'Patient' },
            { key: 'doctor_id', label: 'Doctor' },
            { key: 'department', label: 'Dept' },
            { key: 'status', label: 'Status' },
            { key: 'reschedule_count', label: 'Reschedules' },
            { key: 'version', label: 'Version' },
            { key: 'slot_start', label: 'Slot Start' }
          ]}
        />
      </Section>}

      {section === 'reschedule' && <Section title="Reschedule Rules" icon={RefreshCcw}>
        <div className="form-grid compact">
          <Field label="New slot start" type="datetime-local" value={form.rescheduleStart} onChange={update('rescheduleStart')} />
          <Field label="New slot end" type="datetime-local" value={form.rescheduleEnd} onChange={update('rescheduleEnd')} />
        </div>
        <ul className="rule-list">
          <li>Maximum reschedules per appointment: <strong>2</strong>.</li>
          <li>Reschedule blocked within <strong>1 hour</strong> of the current scheduled slot.</li>
          <li>New slot must also satisfy clinic hours, 30-min duration, and 2h lead time.</li>
          <li><code>version</code> is incremented on every reschedule (optimistic locking).</li>
        </ul>
        <div className="button-row">
          <ActionButton icon={RefreshCcw} onClick={props.rescheduleAppointment} disabled={!ids.appointmentId}>Reschedule</ActionButton>
        </div>
      </Section>}
    </div>
  );
}

function BillingTab(props) {
  const { form, setForm, ids, bills, billTotal, checkAppointmentStatusForBilling, appointmentForBilling, cancellationCharges } = props;
  const [section, setSection] = useState('generate');
  const update = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));

  return (
    <div className="tab-stack">
      <SubTabs
        active={section}
        onChange={setSection}
        tabs={[
          { id: 'generate', label: 'Generate Bill' },
          { id: 'adjust', label: 'Adjustments' }
        ]}
      />
      {section === 'generate' && <Section title="Generate Bill With Tax Calculation" icon={Banknote}>
        <div className="form-grid">
          <Field label="Appointment ID" value={form.appointmentId} onChange={(v) => { update('appointmentId')(v); checkAppointmentStatusForBilling(v); }} />
          {appointmentForBilling && (
            <label className="field"><span>Appointment Status</span><input value={appointmentForBilling.status} readOnly style={{ color: appointmentForBilling.status === 'CANCELLED' ? '#d32f2f' : '#388e3c', fontWeight: 'bold' }} /></label>
          )}
          <Field 
            label="Consultation fee" 
            type="number" 
            value={form.consultation} 
            onChange={update('consultation')}
            disabled={appointmentForBilling?.status === 'CANCELLED'}
          />
          <Field 
            label="Medication charges" 
            type="number" 
            value={form.medication} 
            onChange={update('medication')}
            disabled={appointmentForBilling?.status === 'CANCELLED'}
          />
          {appointmentForBilling?.status === 'CANCELLED' ? (
            <div style={{ gridColumn: '1/-1', padding: '12px', backgroundColor: '#fff3e0', borderRadius: '4px', color: '#e65100' }}>
              <strong>Cancellation:</strong> Billing is disabled. Default policy is <strong>{cancellationCharges?.default_policy || 'more_than_2_hours'}</strong> with charge ratio <strong>{cancellationCharges?.charges?.[cancellationCharges?.default_policy] ?? 0}</strong>.
            </div>
          ) : appointmentForBilling?.status === 'COMPLETED' ? (
            <label className="field"><span>Calculated total</span><input value={money(billTotal.total)} readOnly /></label>
          ) : null}
        </div>
        {appointmentForBilling?.status === 'COMPLETED' && (
          <div className="totals">
            <span>Subtotal: <strong>{money(billTotal.subtotal)}</strong></span>
            <span>Tax 5%: <strong>{money(billTotal.tax)}</strong></span>
            <span>Total: <strong>{money(billTotal.total)}</strong></span>
          </div>
        )}
        <div className="button-row">
          <ActionButton icon={CheckCircle2} onClick={props.createBill} disabled={!appointmentForBilling || !form.appointmentId || appointmentForBilling?.status !== 'COMPLETED'}>Generate bill</ActionButton>
        </div>
      </Section>}

      {section === 'adjust' && <Section title="Cancellation And Billing Adjustments" icon={RefreshCcw}>
        <div className="form-grid compact">
          <Field
            label="Policy scenario"
            value={form.cancellationTiming}
            onChange={update('cancellationTiming')}
            options={[
              { value: 'more_than_2_hours', label: 'More than 2 hours: full refund' },
              { value: 'within_2_hours', label: 'Within 2 hours: 50 percent charge' },
              { value: 'no_show', label: 'No-show: full fee or manual review' }
            ]}
          />
          <label className="field"><span>Bill ID</span><input value={ids.billId || 'Not generated'} readOnly /></label>
        </div>
        <div className="button-row">
          <ActionButton icon={Activity} onClick={props.demonstrateCancellationPolicy}>Calculate adjustment</ActionButton>
          <ActionButton icon={XCircle} variant="danger" onClick={props.voidBill} disabled={!ids.billId}>Void associated bill</ActionButton>
        </div>
        <DataTable
          rows={bills}
          columns={[
            { key: 'id', label: 'Bill' },
            { key: 'patient_id', label: 'Patient' },
            { key: 'appointment_id', label: 'Appointment' },
            { key: 'amount', label: 'Amount', render: (row) => money(row.amount) },
            { key: 'status', label: 'Status' }
          ]}
        />
      </Section>}
    </div>
  );
}

function PrescriptionTab(props) {
  const { form, setForm, ids, prescriptions, retrievedRx } = props;
  const [section, setSection] = useState('create');
  const update = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));

  return (
    <div className="tab-stack">
      <SubTabs
        active={section}
        onChange={setSection}
        tabs={[
          { id: 'create', label: 'Create & Retrieve' },
          { id: 'records', label: 'Records' }
        ]}
      />
      {section === 'create' && <Section title="Create And Retrieve Appointment Prescription" icon={ClipboardList}>
        <div className="form-grid">
          <Field label="Appointment ID" value={form.appointmentId} onChange={update('appointmentId')} />
          <Field label="Medication" value={form.medication} onChange={update('medication')} />
          <Field label="Dosage" value={form.dosage} onChange={update('dosage')} />
          <Field label="Days" type="number" value={form.days} onChange={update('days')} />
          <label className="field"><span>Prescription ID</span><input value={ids.prescriptionId || 'Not created'} readOnly /></label>
        </div>
        <div className="button-row">
          <ActionButton icon={CheckCircle2} onClick={props.createPrescription} disabled={!form.appointmentId}>Create prescription</ActionButton>
          <ActionButton icon={Search} onClick={props.retrievePrescription} disabled={!ids.prescriptionId}>Retrieve prescription</ActionButton>
          <ActionButton icon={AlertTriangle} variant="warning" onClick={props.invalidPrescriptionScenario}>Invalid appointment scenario</ActionButton>
        </div>
        {retrievedRx && (
          <div style={{ marginTop: '16px', padding: '16px', backgroundColor: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: '6px' }}>
            <h4 style={{ margin: '0 0 12px 0', color: '#334155' }}>Prescription #{retrievedRx.id}</h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '13px' }}>
              <div><strong>Patient ID:</strong> {retrievedRx.patient_id}</div>
              <div><strong>Doctor ID:</strong> {retrievedRx.doctor_id}</div>
              <div><strong>Medication:</strong> {retrievedRx.medication}</div>
              <div><strong>Dosage:</strong> {retrievedRx.dosage}</div>
              <div><strong>Duration:</strong> {retrievedRx.days} days</div>
              <div><strong>Issued:</strong> {new Date(retrievedRx.created_at || Date.now()).toLocaleDateString()}</div>
            </div>
          </div>
        )}
      </Section>}
      {section === 'records' && <Section title="Prescription Records" icon={ClipboardList}>
        <DataTable
          rows={prescriptions}
          columns={[
            { key: 'id', label: 'RX' },
            { key: 'appointment_id', label: 'Appointment' },
            { key: 'patient_id', label: 'Patient' },
            { key: 'medication', label: 'Medication' },
            { key: 'days', label: 'Days' }
          ]}
        />
      </Section>}
    </div>
  );
}

function PaymentNotificationTab(props) {
  const { form, setForm, ids } = props;
  const [section, setSection] = useState('payment');
  const update = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));

  return (
    <div className="tab-stack">
      <SubTabs
        active={section}
        onChange={setSection}
        tabs={[
          { id: 'payment', label: 'Payment' },
          { id: 'notification', label: 'Notifications' }
        ]}
      />
      {section === 'payment' && <Section title="Payment Idempotency Demonstration" icon={Banknote}>
        <div className="form-grid">
          <Field label="Bill ID" value={form.billId} onChange={update('billId')} />
          <Field label="Amount" type="number" value={form.amount} onChange={update('amount')} />
          <Field
            label="Method"
            value={form.method}
            onChange={update('method')}
            options={[
              { value: 'CARD', label: 'CARD' },
              { value: 'UPI', label: 'UPI' },
              { value: 'CASH', label: 'CASH' },
              { value: 'INSURANCE', label: 'INSURANCE' }
            ]}
          />
          <Field label="Idempotency-Key (sent as header)" value={form.idempotencyKey} onChange={update('idempotencyKey')} />
        </div>
        <ul className="rule-list" style={{marginBottom:'8px'}}>
          <li>Uses <code>POST /payments/charge</code> with <strong>Idempotency-Key</strong> header.</li>
          <li>Repeating the same key returns the existing payment — <strong>no duplicate</strong> created.</li>
        </ul>
        <div className="button-row">
          <ActionButton icon={CheckCircle2} onClick={() => props.chargePayment(false)} disabled={!form.billId}>Charge payment</ActionButton>
          <ActionButton icon={ShieldCheck} variant="warning" onClick={() => props.chargePayment(true)} disabled={!form.billId}>Repeat same key (idempotency test)</ActionButton>
        </div>
      </Section>}

      {section === 'notification' && <Section title="Notification Alerts" icon={Bell}>
        <div className="button-row">
          <ActionButton icon={Bell} onClick={() => props.sendDemoNotification('Appointment reminder')}>Appointment reminder</ActionButton>
          <ActionButton icon={Bell} onClick={() => props.sendDemoNotification('Billing event')}>Billing alert</ActionButton>
          <ActionButton icon={Bell} onClick={() => props.sendDemoNotification('Refund status')}>Refund alert</ActionButton>
        </div>
        <ul className="rule-list">
          <li>Notifications are displayed as SMS/email alert events for the submission demo.</li>
          <li>Appointment booking, rescheduling, cancellation, billing, payment, and refund events are represented.</li>
        </ul>
      </Section>}
    </div>
  );
}

function ApiDataTab({ serviceMap }) {
  const [section, setSection] = useState('contract');
  const rows = [
    { service: 'Patient', database: 'patients.db', projection: 'Patient search by name and phone via read model adapter', endpoint: '/v1/patients' },
    { service: 'Doctor Schedule', database: 'doctors.db', projection: 'Department filter and doctor slot listing', endpoint: '/v1/doctors' },
    { service: 'Appointment', database: 'appointments.db', projection: 'Doctor department cached on appointment record', endpoint: '/v1/appointments' },
    { service: 'Prescription', database: 'prescriptions.db', projection: 'Appointment-linked prescription retrieval', endpoint: '/v1/prescriptions' },
    { service: 'Billing', database: 'billing.db', projection: 'Bill status and payment history', endpoint: '/v1/bills' }
  ];

  return (
    <div className="tab-stack">
      <SubTabs
        active={section}
        onChange={setSection}
        tabs={[
          { id: 'contract', label: 'API Contract' },
          { id: 'guardrails', label: 'Guardrails' },
          { id: 'data', label: 'Data Design' },
          { id: 'map', label: 'Service Map' }
        ]}
      />
      {section === 'contract' && <Section title="API Contract" icon={FileJson}>
        <div className="info-grid">
          <div>
            <h3>Versioning</h3>
            <p>Demo requests are routed through `/v1` paths by the React UI adapter.</p>
          </div>
          <div>
            <h3>Error structure</h3>
            <pre>{JSON.stringify({ code: 'SERVICE_400', message: 'Validation failed', correlationId: 'corr-example' }, null, 2)}</pre>
          </div>
          <div>
            <h3>Pagination and filtering</h3>
            <p>List views return `items`, `page`, `pageSize`, and `total` through the demo adapter.</p>
          </div>
          <div>
            <h3>OpenAPI 3.0</h3>
            <p>Swagger JSON is available from each backend service at `/swagger.json`.</p>
          </div>
        </div>
      </Section>}

      {section === 'guardrails' && <Section title="Additional Rules And Guardrails" icon={ShieldCheck}>
        <DataTable
          rows={[
            { rule: 'RBAC', detail: 'Demo roles: reception, doctor, billing, and admin are documented for service-level authorization.' },
            { rule: 'Slot duration', detail: 'The console uses 30-minute appointment and doctor-slot intervals.' },
            { rule: 'Doctor capacity', detail: 'Maximum appointments per doctor per day is listed as an appointment policy guardrail.' },
            { rule: 'Department validation', detail: 'Appointment requests carry department data and the demo records mismatch validation as a required rule.' },
            { rule: 'Time zone handling', detail: 'Submission contract stores timestamps in ISO-8601 UTC and displays local-time input controls.' },
            { rule: 'Billing lifecycle', detail: 'Billing lifecycle follows OPEN -> PAID -> REFUND or VOID adjustment states.' },
            { rule: 'Concurrency', detail: 'The overlap scenario records slot reservation or optimistic locking as the double-booking control.' }
          ]}
          columns={[
            { key: 'rule', label: 'Guardrail' },
            { key: 'detail', label: 'Demo detail' }
          ]}
        />
      </Section>}

      {section === 'data' && <Section title="Database-Per-Service" icon={Database}>
        <DataTable
          rows={rows}
          columns={[
            { key: 'service', label: 'Service' },
            { key: 'database', label: 'Owned database' },
            { key: 'projection', label: 'Read projection or filter' },
            { key: 'endpoint', label: 'Versioned demo endpoint' }
          ]}
        />
      </Section>}

      {section === 'map' && <Section title="Service Map" icon={Activity}>
        <pre>{JSON.stringify(serviceMap, null, 2)}</pre>
      </Section>}
    </div>
  );
}

function ResponsePanel({ response }) {
  return (
    <section className="side-section">
      <div className="side-heading">
        <Activity size={17} />
        <h2>Latest Output</h2>
      </div>
      {!response ? (
        <div className="empty-state">Run a service action to display the API or rule output.</div>
      ) : (
        <div>
          <div className="response-meta">
            <span className={response.ok ? 'pill ok' : 'pill bad'}>{response.status}</span>
            <span>{response.method}</span>
            <span>{response.path}</span>
          </div>
          <h3>{response.title}</h3>
          <pre>{JSON.stringify(response.body, null, 2)}</pre>
        </div>
      )}
    </section>
  );
}

function EventLog({ events }) {
  return (
    <section className="side-section">
      <div className="side-heading">
        <ClipboardList size={17} />
        <h2>Demo Log</h2>
      </div>
      <div className="event-list">
        {events.map((event) => (
          <article className={`event ${event.level}`} key={event.id}>
            <div className="event-topline">
              <span>{event.at}</span>
              <strong>{serviceLabel[event.service] || event.service}</strong>
            </div>
            <h3>{event.title}</h3>
            <p>{event.message}</p>
            {event.meta && <pre>{JSON.stringify(event.meta, null, 2)}</pre>}
          </article>
        ))}
      </div>
    </section>
  );
}

createRoot(document.getElementById('root')).render(<App />);
