import pdfplumber
import json
from django.db import models
from django.core.mail import send_mail
from django.conf import settings
from rest_framework import status, views, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from .models import CandidateProfile, Resume, Skill, Job, JobApplication, MatchScore, HRProfile, UserProfile
from .serializers import (
    UserSerializer, CandidateProfileSerializer, ResumeSerializer, 
    JobSerializer, JobApplicationSerializer, HRProfileSerializer
)
from .ai_utils import (
    parse_resume_ai, polish_summary_ai, match_job_ai, 
    generate_jd_ai, generate_interview_questions_ai
)

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data['role'] = self.user.user_profile.role
        data['username'] = self.user.username
        data['email'] = self.user.email
        return data

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                "user": serializer.data,
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "role": user.user_profile.role
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    permission_classes = [permissions.AllowAny]

class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        try:
            role = self.request.user.user_profile.role
            if role == 'hr':
                return HRProfileSerializer
            return CandidateProfileSerializer
        except:
            return CandidateProfileSerializer

    def get_object(self):
        try:
            role = self.request.user.user_profile.role
            if role == 'hr':
                return self.request.user.hr_profile
            return self.request.user.profile
        except:
            # Fallback for old users or missing profiles
            if not hasattr(self.request.user, 'user_profile'):
                UserProfile.objects.get_or_create(user=self.request.user, role='job_seeker')
            
            role = self.request.user.user_profile.role
            if role == 'hr':
                profile, _ = HRProfile.objects.get_or_create(user=self.request.user)
                return profile
            else:
                profile, _ = CandidateProfile.objects.get_or_create(user=self.request.user)
                return profile

class ResumeUploadView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        file_obj = request.data.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        # Save Resume
        profile = request.user.profile
        resume = Resume.objects.create(candidate=profile, file=file_obj)

        # Extract Text
        raw_text = ""
        with pdfplumber.open(resume.file.path) as pdf:
            for page in pdf.pages:
                raw_text += page.extract_text() or ""

        resume.raw_text = raw_text
        resume.save()

        # AI Parsing
        structured_data = parse_resume_ai(raw_text)
        resume.structured_data = structured_data
        resume.save()

        # Update Profile
        profile.full_name = structured_data.get('Full Name', profile.full_name)
        profile.email = structured_data.get('Email', profile.email)
        profile.phone = structured_data.get('Phone', profile.phone)
        profile.summary = structured_data.get('Summary', profile.summary)
        profile.experience = structured_data.get('Experience', [])
        profile.education = structured_data.get('Education', [])
        
        # Handle Skills
        skills_list = structured_data.get('Skills', [])
        for skill_name in skills_list:
            skill, _ = Skill.objects.get_or_create(name=skill_name.lower().strip())
            profile.skills.add(skill)
        
        profile.save()

        return Response(CandidateProfileSerializer(profile).data, status=status.HTTP_201_CREATED)

class GuestResumeUploadView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        file_obj = request.data.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        # Extract Text
        raw_text = ""
        try:
            import io
            file_obj.seek(0)
            with pdfplumber.open(io.BytesIO(file_obj.read())) as pdf:
                for page in pdf.pages:
                    raw_text += page.extract_text() or ""
            
            if not raw_text.strip():
                return Response({"error": "Could not extract text from PDF"}, status=status.HTTP_400_BAD_REQUEST)

            # AI Parsing
            structured_data = parse_resume_ai(raw_text)
            return Response(structured_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PolishSummaryView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        summary = request.data.get('summary')
        if not summary:
            return Response({"error": "No summary provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        polished = polish_summary_ai(summary)
        return Response({"polished": polished})

class JobListCreateView(generics.ListCreateAPIView):
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        role = getattr(self.request.user.user_profile, 'role', 'job_seeker')
        if role == 'hr':
            return Job.objects.filter(recruiter=self.request.user).order_by('-created_at')
        return Job.objects.all().order_by('-created_at')

    def perform_create(self, serializer):
        company = "Local Corp"
        if hasattr(self.request.user, 'hr_profile'):
            company = self.request.user.hr_profile.company_name or company
        serializer.save(recruiter=self.request.user, company=company)

class JobDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Allow anyone to view, but only recruiter can edit/delete
        if self.request.method in permissions.SAFE_METHODS:
            return Job.objects.all()
        return Job.objects.filter(recruiter=self.request.user)


class JobApplyView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        job_id = request.data.get('job_id')
        if not job_id:
            return Response({"error": "job_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            job = Job.objects.get(id=job_id)
            profile = request.user.profile
            application, created = JobApplication.objects.get_or_create(
                job=job, candidate=profile
            )
            if created:
                return Response({"message": "Application submitted successfully", "status": "Applied"}, status=status.HTTP_201_CREATED)
            return Response({"message": "You have already applied for this job", "status": application.status}, status=status.HTTP_200_OK)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)


class JobMatchView(views.APIView):

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        job_id = request.query_params.get('job_id')
        if not job_id:
            return Response({"error": "job_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            job = Job.objects.get(id=job_id)
            profile = request.user.profile
            
            application, created = JobApplication.objects.get_or_create(
                job=job, candidate=profile
            )
            
            # Recalculate match score every time or handle as needed
            user_skills = set(s.name.lower() for s in profile.skills.all())
            job_skills = set(s.name.lower() for s in job.required_skills.all())
            
            if not job_skills:
                match_percentage = 100.0
                missing_skills = []
            else:
                shared_skills = user_skills.intersection(job_skills)
                match_percentage = (len(shared_skills) / len(job_skills)) * 100
                missing_skills = list(job_skills - user_skills)
            
            # Mock or AI Explanation
            explanation = f"You matched {len(shared_skills)} out of {len(job_skills)} required skills."
            if match_percentage < 100:
                explanation += f" Consider learning: {', '.join(missing_skills[:3])}."

            if hasattr(application, 'match_score'):
                application.match_score.score = match_percentage
                application.match_score.explanation = explanation
                application.match_score.missing_skills = missing_skills
                application.match_score.save()
            else:
                MatchScore.objects.create(
                    application=application,
                    score=match_percentage,
                    explanation=explanation,
                    missing_skills=missing_skills
                )
            
            return Response(JobApplicationSerializer(application).data)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)


class InterviewPrepView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        job_id = request.data.get('job_id')
        job = Job.objects.get(id=job_id)
        profile = request.user.profile
        
        resume_data = {
            'skills': [s.name for s in profile.skills.all()],
            'experience': profile.experience
        }
        questions = generate_interview_questions_ai(resume_data, job.description)
        return Response({"questions": questions})

class GenerateJDView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        title = request.data.get('title')
        prompt = request.data.get('prompt', '')
        if not title:
            return Response({"error": "Job title is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        jd = generate_jd_ai(f"Title: {title}. Context: {prompt}")
        return Response({"description": jd})

class JobApplicationDetailView(generics.RetrieveAPIView):
    queryset = JobApplication.objects.all()
    serializer_class = JobApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Ensure only recruiters of the job or the candidate can see this
        return JobApplication.objects.filter(
            models.Q(job__recruiter=self.request.user) | 
            models.Q(candidate__user=self.request.user)
        )

class RecruiterApplicationsListView(generics.ListAPIView):
    serializer_class = JobApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        role = getattr(self.request.user.user_profile, 'role', 'job_seeker')
        if role == 'hr':
            return JobApplication.objects.filter(job__recruiter=self.request.user).order_by('-applied_at')
        return JobApplication.objects.filter(candidate__user=self.request.user).order_by('-applied_at')

class UpdateApplicationStatusView(views.APIView):

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            application = JobApplication.objects.get(pk=pk)
            if application.job.recruiter != request.user:
                return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
            status_val = request.data.get('status')
            if status_val not in ['Shortlisted', 'Rejected']:
                return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)
            
            application.status = status_val
            application.save()

            try:
                subject = f"Update regarding your application for {application.job.title}"
                message = f"Hi {application.candidate.full_name},\n\nYour application for {application.job.title} at {application.job.company} has been marked as: {status_val}.\n\nBest regards,\nHiring Team"
                recipient_list = [application.candidate.user.email]
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)
            except Exception as e:
                print(f"Email failed: {e}")

            return Response(JobApplicationSerializer(application).data)
        except JobApplication.DoesNotExist:
            return Response({"error": "Application not found"}, status=status.HTTP_404_NOT_FOUND)

class RecruiterAnalyticsView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        role = getattr(request.user.user_profile, 'role', 'job_seeker')
        if role != 'hr':
            return Response({"error": "Only recruiters can view analytics"}, status=403)

        jobs = Job.objects.filter(recruiter=request.user)
        total_jobs = jobs.count()
        applications = JobApplication.objects.filter(job__in=jobs)
        total_candidates = applications.values('candidate').distinct().count()
        
        avg_score = MatchScore.objects.filter(application__in=applications).aggregate(avg=models.Avg('score'))['avg'] or 0
        
        return Response({
            "total_candidates": total_candidates,
            "total_jobs": total_jobs,
            "avg_score": round(avg_score, 2),
            "recent_applications": JobApplicationSerializer(applications.order_by('-match_score__score')[:10], many=True).data
        })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def api_root(request):
    return Response({
        "message": "Welcome to AIVault API",
        "endpoints": {
            "auth": "/api/auth/",
            "profile": "/api/profile/",
            "jobs": "/api/jobs/",
            "resume": "/api/resume/"
        }
    })
